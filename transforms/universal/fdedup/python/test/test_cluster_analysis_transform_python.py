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

from cluster_analysis_transform import sort_output_cli_param
from cluster_analysis_transform_python import (
    ClusterAnalysisPythonTransformConfiguration,
)
from data_processing.runtime.pure_python import PythonTransformLauncher
from data_processing.test_support.launch.transform_test import (
    AbstractTransformLauncherTest,
)


class TestPythonClusterAnalysisTransform(AbstractTransformLauncherTest):
    """
    Extends the super-class to define the test data for the tests defined there.
    The name of this class MUST begin with the word Test so that pytest recognizes it as a test class.
    """

    def get_test_transform_fixtures(self) -> list[tuple]:
        basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../test-data"))
        config = {
            "cluster_num_bands": 14,
            "cluster_num_segments": 2,
            "cluster_jaccard_similarity_threshold": 0.7,
            sort_output_cli_param: True,
        }
        launcher = PythonTransformLauncher(ClusterAnalysisPythonTransformConfiguration())
        fixtures = [
            (
                launcher,
                config,
                basedir + "/expected/signature_calc/bands",
                basedir + "/expected/cluster_analysis/docs_to_remove",
            )
        ]
        return fixtures
