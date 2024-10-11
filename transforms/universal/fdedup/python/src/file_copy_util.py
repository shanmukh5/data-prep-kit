import argparse
import io
import os
import re

import polars as pl
from data_processing.data_access import DataAccessFactory, DataAccessFactoryBase
from data_processing.utils import ParamsUtils, get_logger


"""
This class reads all the parquet files inside an `input_folder` of the type
`.../bands/band=b/segment=s`, concatenates those files, and writes them into a
file called `.../consolidated_bands/band_b_segment_s.parquet`
"""


class FileCopyUtil:
    def __init__(
        self,
        data_access_factory: DataAccessFactoryBase,
        config: dict,
        stats: dict,
    ):
        self.data_access_factory = data_access_factory
        self.root_folder = config.get("root_folder")
        self.logger = get_logger(__name__, level="INFO")

    def copy_data(self, subfolder_name: str, data_type: str):
        self.logger.info(f"copy_data(): subfolder_name = {subfolder_name}, data_type = {data_type}")
        if self.data_access_factory.s3_config is not None:
            _, root_folder = self.root_folder.split("://")
        else:
            root_folder = self.root_folder
        self.logger.debug(f"copy_data(): root_folder = {root_folder}")
        if data_type == "bands":
            match = re.match(r"^band=(\d+)/segment=(\d+)$", subfolder_name)
            if match:
                band = int(match.group(1))
                segment = int(match.group(2))
            else:
                raise ValueError(f"Wrong subfolder_name {subfolder_name}, should be band=b/segment=s")
            input_folder = os.path.join(
                root_folder,
                "bands",
                f"band={band}",
                f"segment={segment}/",
            )
            output_path = os.path.join(
                root_folder,
                "bands_consolidated",
                f"band_{band}_segment_{segment}.parquet",
            )
        elif data_type == "docs_to_remove":
            input_folder = os.path.join(
                root_folder,
                f"{subfolder_name}/",
            )
            output_path = os.path.join(
                root_folder,
                "docs_to_remove_consolidated",
                f"docs_to_remove_consolidated.parquet",
            )
            self.logger.debug(f"copy_data(): input_folder = {input_folder}, output_path = {output_path}")

        data_access = self.data_access_factory.create_data_access()
        self.logger.debug(f"copy_data(): getting the data from the input_folder {input_folder}")
        file_dict, status = data_access.get_folder_files(
            input_folder,
            extensions=[".parquet"],
            return_data=True,
        )
        self.logger.info(f"Found {len(file_dict)} files in input folder {input_folder}")
        consolidated_df = pl.DataFrame()
        for fname, contents in file_dict.items():
            df = pl.read_parquet(io.BytesIO(contents))
            # self.logger.info(f"{fname} has {len(df)} rows")
            consolidated_df = consolidated_df.vstack(df)
        if "docs_to_remove" in consolidated_df.columns:
            consolidated_df = consolidated_df.select("docs_to_remove").unique()
        output_table = consolidated_df.to_arrow()
        self.logger.info(
            f"Writing to {output_path} table with {output_table.num_rows} rows and {output_table.nbytes:,d} bytes"
        )
        stats = {
            "input_files": len(file_dict),
            "input_bytes": sum(len(v) for v in file_dict.values()),
            "input_rows": output_table.num_rows,
            "output_files": 1,
            "output_bytes": output_table.nbytes,
            "output_rows": output_table.num_rows,
        }
        data_access.save_table(output_path, output_table)
        return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root_folder",
        type=str,
        default=os.getenv("HOME", os.path.join(os.sep)),
        help="root folder",
    )
    parser.add_argument(
        "--subfolder_name",
        type=str,
        default=os.path.join("band=0", "segment=0"),
        help="subfolder name",
    )
    parser.add_argument(
        "--data_type",
        type=str,
        default="docs_to_remove",
        help="Processing either bands or docs_to_remove",
    )
    parser.add_argument(
        "--use_s3",
        type=bool,
        default=False,
        help="use s3",
    )
    args = parser.parse_args()
    root_folder = args.root_folder
    config = {"root_folder": args.root_folder}
    input_folder = args.root_folder
    output_folder = args.root_folder
    data_type = args.data_type
    data_access_factory: DataAccessFactoryBase = DataAccessFactory()
    daf_args = []
    if args.use_s3:
        s3_creds = {
            "access_key": os.getenv("AWS_ACCESS_KEY_ID"),
            "secret_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "url": os.getenv("AWS_ENDPOINT_URL"),
        }
        s3_config = {
            "input_folder": root_folder,
            "output_folder": root_folder,
        }
        daf_args.append("--data_s3_cred")
        daf_args.append(ParamsUtils.convert_to_ast(s3_creds))
        daf_args.append("--data_s3_config")
        daf_args.append(ParamsUtils.convert_to_ast(s3_config)),
    else:
        local_config = {
            "input_folder": root_folder,
            "output_folder": root_folder,
        }
        daf_args.append("--data_local_config")
        daf_args.append(ParamsUtils.convert_to_ast(local_config))
    daf_parser = argparse.ArgumentParser()
    data_access_factory.add_input_params(parser=daf_parser)
    data_access_factory_args = daf_parser.parse_args(args=daf_args)
    data_access_factory.apply_input_params(args=data_access_factory_args)
    stats = {}
    fcu = FileCopyUtil(data_access_factory=data_access_factory, config=config, stats=stats)
    fcu.copy_data(args.subfolder_name, args.data_type)
