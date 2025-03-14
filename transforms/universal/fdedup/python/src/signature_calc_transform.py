# (C) Copyright IBM Corp. 2024.
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#  http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
################################################################################
import os
import re
import unicodedata
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

import mmh3
import numpy as np
import polars as pl
import pyarrow as pa
from data_processing.data_access import DataAccessFactory
from data_processing.transform import AbstractTableTransform, TransformConfiguration
from data_processing.utils import CLIArgumentProvider, UnrecoverableException
from Murmur_MH import Murmur_MH


short_name = "minhash"
cli_prefix = f"{short_name}_"

# configuration keys
document_id_column_key = "document_id_column"
""" This key holds the name of the column storing the unique ID assigned to each document"""
contents_column_key = "contents_column"
""" This key holds the name of the column storing the contents of each document"""
seed_key = "seed"
""" This key holds the seed used to instantiate the random number generator"""
num_permutations_key = "num_permutations"
""" This key holds the number of permutations that determine how many minhashes to calculate for each document"""
num_bands_key = "num_bands"
""" This key holds the number of bands to use in the banding technique"""
num_minhashes_per_band_key = "num_minhashes_per_band"
""" This key holds the number of minhashes to use in each band"""
jaccard_similarity_threshold_key = "jaccard_similarity_threshold"
""" This key holds the Jaccard similarity threshold above which two documents are duplicates"""
word_shingle_size_key = "word_shingle_size"
""" This key holds the size of the word shingles calculated for each document"""
num_segments_key = "num_segments"
""" This key holds the number of segments across which we divide the hashing space for each band"""
shingle_option_key = "shingle_option"
""" This key holds the option that is used to do shingles calculation for each document"""

# command line arguments
document_id_column_cli_param = f"{cli_prefix}{document_id_column_key}"
""" Name of the column storing the unique ID assigned to each document"""
contents_column_cli_param = f"{cli_prefix}{contents_column_key}"
""" Name of the column storing the contents of each document"""
seed_cli_param = f"{cli_prefix}{seed_key}"
""" The seed used to instantiate the random number generator"""
num_permutations_cli_param = f"{cli_prefix}{num_permutations_key}"
""" Number of permutations that determine how many minhashes to calculate for each document"""
num_bands_cli_param = f"{cli_prefix}{num_bands_key}"
""" The number of bands to use in the banding technique"""
num_minhashes_per_band_cli_param = f"{cli_prefix}{num_minhashes_per_band_key}"
""" The number of minhashes to use in each band"""
jaccard_similarity_threshold_cli_param = f"{cli_prefix}{jaccard_similarity_threshold_key}"
""" Jaccard similarity threshold above which two documents are duplicates"""
word_shingle_size_cli_param = f"{cli_prefix}{word_shingle_size_key}"
""" The size of the word shingles calculated for each document"""
num_segments_cli_param = f"{cli_prefix}{num_segments_key}"
""" The number of segments across which we divide the hashing space for each band"""
shingle_option_cli_param = f"{cli_prefix}{shingle_option_key}"
""" The option (word/char) used to do shingles calculation for each document"""

captured_arg_keys = [
    document_id_column_key,
    contents_column_key,
    seed_key,
    num_bands_key,
    num_minhashes_per_band_key,
    num_permutations_key,
    jaccard_similarity_threshold_key,
    word_shingle_size_key,
    num_segments_key,
    shingle_option_key,
]

# defaults
document_id_column_default = "int_id_column"
""" Default name of the column storing the unique ID assigned to each document"""
contents_column_default = "contents"
""" Default name of the column storing the contents of each document"""
seed_default = 42
""" Default seed used to instantiate the random number generator"""
num_permutations_default = 112
""" Default number of minhashes used for each document (from FineWeb https://arxiv.org/pdf/2406.17557)"""
num_bands_default = 14
""" Default number of bands to use in the banding technique (from FineWeb https://arxiv.org/pdf/2406.17557)"""
num_minhashes_per_band_default = 8
""" Default number of minhashes to use in each band (from FineWeb https://arxiv.org/pdf/2406.17557)"""
word_shingle_size_default = 5
""" Default size of the word shingles (from FineWeb https://arxiv.org/pdf/2406.17557)"""
jaccard_similarity_threshold_default = 0.75
""" Default Jaccard similarity threshold (from FineWeb https://arxiv.org/pdf/2406.17557)"""
num_segments_default = 1
""" Default number of segments across which we divide the hashing space for each band"""
shingle_option_default = "word"
""" Default option of doing shingling"""


sigcalc_data_factory_key = "sc_data_factory"
sigcalc_data_access_key = "sc_data_access"


NUMBERS_PATTERN = re.compile(r"\d+(\.\d+)?")
WHITESPACE_PATTERN = re.compile(r"\s+")
PUNCTUATION = "!/—”:％１〈&(、━\\【#%「」，】；+^]~“《„';’{|∶´[=-`*．（–？！：$～«〉,><》)?）。…@_.\"}►»" + "".join(
    map(
        chr,
        (x for a, b in ((0, 9), (11, 13), (13, 32), (127, 160)) for x in range(a, b)),
    )
)
PUNCTUATION_SET = set(PUNCTUATION)
PUNCTUATION_TRANS = str.maketrans(PUNCTUATION, " " * len(PUNCTUATION))


class SignatureCalculationTransform(AbstractTableTransform):
    """
    This is the first transform of the fuzzy dedup pipeline. First, it calculates,
    for each document in a dataset, `num_permutations` minhashes.  It accepts as
    input the number of bands and the length (number of minhashes used for) each
    band. The band signatures, the minhashes and the document lengths are
    then saved in the output folder, under a folder structure `bands/band=b/segment=s`.
    To improve scalability of the next step of fuzzy dedup, the hash space of
    each band is divided into `num_segments` segments.

    The following internal variables are retrieved from the config parameter:
        document_id_column: name of the column storing the unique ID assigned to each document
        contents_column_cli_param: name of the column storing the contents of each document
        seed: the seed used to instantiate the random number generator
        num_permutations: number of minhashes to calculate for each document
        num_bands: number of bands to use for banding technique
        num_minhashes_per_band: number of minhashes to use in each band
        jaccard_similarity_threshold: Jaccard similarity threshold above which two documents are duplicates
        word_shingle_size: the size of the word shingles calculated for each document
        num_segments: the number of segments across which we divide the hashing space for each band
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize based on the dictionary of configuration information.
        This is generally called with configuration parsed from the CLI arguments defined
        by the companion runtime, SignatureCalculationTransformRuntime.  If running inside the RayMutatingDriver,
        these will be provided by that class with help from the RayMutatingDriver.
        """
        super().__init__(config)
        self.document_id_column = config.get(document_id_column_key, document_id_column_default)
        self.contents_column = config.get(contents_column_key, contents_column_default)
        self.seed = config.get(seed_key, seed_default)
        self.num_permutations = config.get(num_permutations_key, num_permutations_default)
        self.jaccard_similarity_threshold = config.get(
            jaccard_similarity_threshold_key, jaccard_similarity_threshold_default
        )
        self.word_shingle_size = config.get(word_shingle_size_key, word_shingle_size_default)
        self.num_segments = config.get(num_segments_key, num_segments_default)
        self.num_bands = config.get(num_bands_key, num_bands_default)
        self.num_rows = config.get(num_minhashes_per_band_key, num_minhashes_per_band_default)
        self.shingle_option = config.get(shingle_option_key, shingle_option_default)
        # use this dataframe to store the minhashes and size for each document
        self.all_minhashes = None
        # use this dataframe to store the band hashes for each document
        self.all_band_hashes = None
        # this variable keeps track of how many files were processed since last
        # data write to properly update metadata
        self.files_processed = 0
        self.bytes_processed = 0
        self.data_access = config.get("data_access")
        if self.data_access is None:
            raise UnrecoverableException("Could not get a pointer to the data access object inside the transform.")
        self.last_file_name = None

        self.sc_data_access = config.get(sigcalc_data_access_key, None)
        self.sc_daf = config.get(sigcalc_data_factory_key, None)
        if self.sc_daf is None:
            raise RuntimeError(f"Missing configuration value for key {sigcalc_data_factory_key}")

    def transform(self, table: pa.Table, file_name: str = None) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Put Transform-specific to convert one Table to 0 or more tables. It also returns
        a dictionary of execution statistics - arbitrary dictionary
        This implementation makes no modifications so effectively implements a copy of the
        input parquet to the output folder, without modification.
        """
        self.logger.debug(f"Transforming table with {table.num_rows} rows from file {file_name}")
        self.logger.debug("----minhash---")
        self.last_file_name = file_name
        self.files_processed += 1
        self.bytes_processed += table.nbytes
        # instantiate with same seed so every worker use same hash functions
        mm_min_hash = Murmur_MH(num_perm=self.num_permutations, seed=self.seed)

        # load the data from pyarrow table
        df = pl.from_arrow(table)
        # read the target columns
        df = df.select(self.contents_column, self.document_id_column)

        # generate minhash values
        minhashes = df.map_rows(
            lambda row: mm_min_hash.minhash2_nosalt(
                *self._generate_word_shingles(row, self.shingle_option, window_size=self.word_shingle_size)
            )
        )
        # rename columns, cast minhashes to list(uint32)
        minhashes = minhashes.select(
            pl.col("column_2").alias(self.document_id_column),
            pl.col("column_0").cast(pl.List(pl.UInt32)).alias("minhashes"),
            pl.col("column_1").alias("document_length"),
        )
        # store the minhash calculations to send out at the end of execution
        if self.all_minhashes is None:
            self.all_minhashes = minhashes
        else:
            self.all_minhashes = self.all_minhashes.vstack(minhashes)

        # Calculate band hashes
        band_hashes_list = self._process_rows_into_bands(
            minhashes,
            self.num_bands,
            self.num_rows,
        )
        band_hash_schema = pl.Schema(
            {
                "band_hash": pl.UInt64,
                "band_index": pl.Int32,
                self.document_id_column: pl.Int64,
            }
        )
        band_hashes = pl.DataFrame(band_hashes_list, schema=band_hash_schema)

        # store the band hash calculations to send out at the end of execution
        if self.all_band_hashes is None:
            self.all_band_hashes = band_hashes
        else:
            self.all_band_hashes = self.all_band_hashes.vstack(band_hashes)

        if len(self.all_minhashes) > 750000:
            tables, metadata = self._write_band_signatures()
        else:
            tables = []
            metadata = {}
        # update metadata stats and return the stats (no tables are returned in transform)
        return tables, metadata

    def flush(self) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        This is supporting method for transformers, that implement buffering of tables, for example coalesce.
        These transformers can have buffers containing tables that were not written to the output. Flush is
        the hook for them to return back locally stored tables and their statistics. The majority of transformers
        should use default implementation.
        If there is an error, an exception must be raised - exit()ing is not generally allowed when running in Ray.
        :return: a tuple of a list of 0 or more converted tables and a dictionary of statistics that will be
        propagated to metadata
        """
        self.logger.info(f"Starting flush()")
        if self.all_band_hashes is not None and self.all_minhashes is not None:
            tables, metadata = self._write_band_signatures()
        else:
            tables = []
            metadata = {}
        return tables, metadata

    def _write_band_signatures(self):
        # define the upper and lower bounds of each band segment
        if self.sc_data_access is None:
            self.sc_data_access = self.sc_daf.create_data_access()
        segment_bounds_list = []
        upper_bound = np.uint64(np.iinfo(np.uint64).max)
        segment_len = np.uint64(upper_bound // self.num_segments)
        for segment_index in range(self.num_segments):
            segment_bounds_list.append(np.uint64(segment_index) * segment_len)
        segment_bounds_list.append(upper_bound)
        segment_bounds = np.array(segment_bounds_list, dtype=np.uint64)
        self.logger.debug(f"Calculated {len(segment_bounds)} segment_bounds")
        # output stats for the metadata
        num_tables_written = 0
        num_docs_written = 0
        num_bytes_written = 0
        self.logger.debug(f"dataframe self.all_band_hashes has {len(self.all_band_hashes)} rows")
        self.logger.debug(f"dataframe self.all_minhashes has {len(self.all_minhashes)} rows")
        # iterate through the bands, get the band hashes for each band, divide
        # them into segments, join with minhashes, and upload to storage
        for band_ix in range(self.num_bands):
            # Filtering on, then dropping the `band_index` column
            band_df = self.all_band_hashes.filter(pl.col("band_index") == band_ix).drop("band_index")
            # assign each band hash to a segment of the hashing space
            self.logger.debug(f"band {band_ix} band_df has {len(band_df)} rows")
            for segment_index in range(self.num_segments):
                segment_band_df = band_df.filter(
                    (pl.col("band_hash") > segment_bounds[segment_index])
                    & (pl.col("band_hash") <= segment_bounds[segment_index + 1])
                )
                self.logger.debug(
                    f"band {band_ix} segment {segment_index} segment_band_df has {len(segment_band_df)} rows"
                )
                # join the band hash dataframe with the minihash and doc length dataframe
                segment_band_minhash_df = segment_band_df.join(
                    self.all_minhashes,
                    on=self.document_id_column,
                    how="inner",
                )
                self.logger.debug(f"band {band_ix} segment {segment_index} joined segment_band_df and minhashes")

                # encapsulate document info in a structure
                segment_band_minhash_df = segment_band_minhash_df.select(
                    pl.col("band_hash"),
                    pl.struct(
                        [
                            pl.col(self.document_id_column),
                            pl.col("minhashes"),
                            pl.col("document_length"),
                        ]
                    ).alias("document_data"),
                )
                self.logger.debug(f"band {band_ix} segment {segment_index} encapsulated document info in a structure")

                # append the table to the result list, and the path to metadata
                last_file_name_path = Path(self.last_file_name)
                suffix_path = last_file_name_path.relative_to(self.data_access.input_folder)
                if self.sc_data_access.output_folder is None:
                    self.sc_data_access.output_folder = self.data_access.output_folder
                save_path = os.path.join(
                    self.sc_data_access.output_folder,
                    "bands",
                    f"band={band_ix}",
                    f"segment={segment_index}",
                    suffix_path,
                )
                segment_band_minhash_table = segment_band_minhash_df.to_arrow()
                bytes_written, _, _ = self.sc_data_access.save_table(save_path, segment_band_minhash_table)
                if bytes_written > 0:
                    num_tables_written += 1
                    num_docs_written += segment_band_minhash_table.num_rows
                    num_bytes_written += bytes_written
                    self.logger.debug(f"Uploaded table for band {band_ix} and segment {segment_index}")
        # add the stats to metadata
        metadata = {
            "input_files": self.files_processed,
            "input_docs": len(self.all_minhashes),
            "input_bytes": self.bytes_processed,
            "output_files": num_tables_written,
            "output_docs": num_docs_written,
            "output_bytes": num_bytes_written,
        }
        self.logger.info(f"Wrote {num_tables_written} tables with a total size of {num_bytes_written:,d} bytes")
        self.files_processed = 0
        self.bytes_processed = 0
        self.all_minhashes = None
        self.all_band_hashes = None
        return [], metadata

    # define shingles generation function
    def _generate_word_shingles(
        self, row: tuple, shingling_option: str, window_size: int = 5, delimiter: str = " "
    ) -> tuple[list, int, int]:
        text = row[0]
        # lower case
        text = text.lower()
        # replace numbers with '0'
        text = NUMBERS_PATTERN.sub("0", text)
        # convert punctuation to spaces
        text = text.translate(PUNCTUATION_TRANS)
        # remove consecutive spaces, newlines, tabs in the middle and in the beginning / end
        text = WHITESPACE_PATTERN.sub(" ", text.strip())
        # diacritics/unicode normalization
        text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
        text = text.strip()
        self.logger.debug(shingling_option)
        if shingling_option == "char":
            words = list(text)
        else:
            words = text.split()
        document_id = row[1]
        doc_len = len(row[0])
        word_count = len(words)
        k_shingles = []
        for i in range(0, max(1, word_count - window_size + 1)):
            k_shingles.append(delimiter.join(words[i : i + window_size]))
        return k_shingles, doc_len, document_id

    def _emit_bands(self, int_id_column: str, minhashes: np.array, b: int, r: int, seed: int = 42):
        num_minhashes = len(minhashes)
        assert b * r <= num_minhashes, f"b*r must be <= num minhashes, was b={b}, r={r}, num_minhashes={num_minhashes}"
        results = []
        for band_index in range(b):
            band_hash, _ = mmh3.hash64(
                minhashes[band_index * r : (band_index + 1) * r],
                seed=seed,
                signed=False,
            )
            results.append((band_hash, band_index, int_id_column))
        return results

    # Apply the function
    def _process_rows_into_bands(self, df, minhashlsh_num_bands, minhashlsh_length_band):
        result = []
        for row in df.iter_rows():
            bands = self._emit_bands(
                row[0],  # document id
                np.array(row[1], dtype=np.uint32),  # minhashes
                minhashlsh_num_bands,
                minhashlsh_length_band,
            )
            for band in bands:
                result.append(band)
        return result


class SignatureCalculationTransformConfiguration(TransformConfiguration):

    """
    Provides support for configuring and using the associated Transform class include
    configuration with CLI args.
    """

    def __init__(self):
        super().__init__(
            name=short_name,
            transform_class=SignatureCalculationTransform,
            remove_from_metadata=[sigcalc_data_factory_key],
        )
        self.daf = DataAccessFactory(cli_arg_prefix="scdata_")

        from data_processing.utils import get_logger

        self.logger = get_logger(__name__, level="INFO")

    def add_input_params(self, parser: ArgumentParser) -> None:
        """
        Add Transform-specific arguments to the given  parser.
        This will be included in a dictionary used to initialize the NOOPTransform.
        By convention a common prefix should be used for all transform-specific CLI args
        (e.g, noop_, pii_, etc.)
        """
        parser.add_argument(
            f"--{document_id_column_cli_param}",
            type=str,
            default=document_id_column_default,
            help="name of the column storing the unique ID assigned to each document",
        )
        parser.add_argument(
            f"--{contents_column_cli_param}",
            type=str,
            default=contents_column_default,
            help="name of the column storing the contents of each document",
        )
        parser.add_argument(
            f"--{seed_cli_param}",
            type=int,
            default=seed_default,
            help="the seed used to instantiate the random number generator",
        )
        parser.add_argument(
            f"--{num_permutations_cli_param}",
            type=int,
            default=num_permutations_default,
            help="number of permutations (minhashes) calculated for each document",
        )
        parser.add_argument(
            f"--{jaccard_similarity_threshold_cli_param}",
            type=float,
            default=jaccard_similarity_threshold_default,
            help="Jaccard similarity threshold above which two documents are duplicates",
        )
        parser.add_argument(
            f"--{word_shingle_size_cli_param}",
            type=int,
            default=word_shingle_size_default,
            help="the size of the word shingles calculated for each document",
        )
        parser.add_argument(
            f"--{num_bands_cli_param}",
            type=int,
            default=num_bands_default,
            help="the number of bands to use in the banding technique",
        )
        parser.add_argument(
            f"--{num_minhashes_per_band_cli_param}",
            type=int,
            default=num_minhashes_per_band_default,
            help="the number of minhashes to use in each band",
        )
        parser.add_argument(
            f"--{num_segments_cli_param}",
            type=int,
            default=num_segments_default,
            help="the number of segments across which we divide the hashing space for each band",
        )
        parser.add_argument(
            f"--{shingle_option_cli_param}",
            type=str,
            default=shingle_option_default,
            help="Shingling option",
        )
        self.daf.add_input_params(parser=parser)

    def apply_input_params(self, args: Namespace) -> bool:
        """
        Validate and apply the arguments that have been parsed
        :param args: user defined arguments.
        :return: True, if validate pass or False otherwise
        """
        captured = CLIArgumentProvider.capture_parameters(args, cli_prefix, False)
        self.params = self.params | captured
        self.logger.info(f"{short_name} parameters are : {self.params}")
        self.params[sigcalc_data_factory_key] = self.daf
        return self.daf.apply_input_params(args=args)
