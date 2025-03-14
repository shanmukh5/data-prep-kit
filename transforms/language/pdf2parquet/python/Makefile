# Define the root of the local git clone for the common rules to be able 
# know where they are running from.
REPOROOT=../../../..

# Set this, before including .make.defaults, to 
#   1 if requirements reference the latest code in the data processing library 
#     in this repo (that is not yet published to pypi).	 This is the default setting.
#   0 if the transforms DPK dependencies are on wheels published to 
#     pypi (e.g. data-prep-toolkit=0.2.1)
#USE_REPO_LIB_SRC=1

# Include a library of common .transform.* targets which most
# transforms should be able to reuse.  However, feel free
# to override/redefine the rules below. 
include $(REPOROOT)/transforms/.make.transforms

# Include the common configuration for this transform
include ../transform.config

RUN_ARGS=" --data_local_config \"{ 'input_folder' : '../test-data/input', 'output_folder' : '../output'}\"  \
	--data_files_to_use \"['.pdf','.zip']\" "

LINUX_WITH_CPU_TORCH?=true
OS := $(shell uname -s)
ifeq ($(OS),Linux)
	ifeq ($(LINUX_WITH_CPU_TORCH),true)
	PIP_INSTALL_EXTRA_ARGS=--extra-index-url=https://download.pytorch.org/whl/cpu
	DOCKER_BUILD_EXTRA_ARGS=--build-arg PIP_INSTALL_EXTRA_ARGS=${PIP_INSTALL_EXTRA_ARGS}
	endif
endif


venv::	.transforms.python-venv

test::	.transforms.python-test

clean:: .transforms.clean

image:: .transforms.python-image

test-src:: .transforms.test-src

setup:: .transforms.setup

build:: build-dist image

publish: publish-image

publish-image:: .transforms.publish-image-python

setup:: .transforms.setup

# distribution versions is the same as image version.
set-versions:
	$(MAKE) TRANSFORM_PYTHON_VERSION=$(PDF2PARQUET_PYTHON_VERSION) TOML_VERSION=$(PDF2PARQUET_PYTHON_VERSION) .transforms.set-versions 
        
build-dist:: .defaults.build-dist 

publish-dist:: .defaults.publish-dist

test-image:: .transforms.python-test-image

run-cli-sample: .transforms.run-cli-python-sample
	$(MAKE) RUN_FILE=$(TRANSFORM_NAME)_transform_python.py \
            RUN_ARGS=" --data_local_config \"{ 'input_folder' : '../test-data/input', 'output_folder' : '../output'}\"  \
				--data_files_to_use \"['.pdf','.zip']\" " \
            .transforms.run-src-file

run-local-sample: .transforms.run-local-sample

run-local-python-sample: .transforms.run-local-python-sample

#run-s3-ray-sample: .transforms.run-s3-ray-sample

minio-start:	.minio-start

kind-load-image:: .transforms.kind-load-image

docker-load-image: .defaults.docker-load-image

docker-save-image: .defaults.docker-save-image
