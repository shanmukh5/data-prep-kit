ARG BASE_IMAGE=docker.io/rayproject/ray:2.24.0-py310

FROM ${BASE_IMAGE}

RUN pip install --upgrade --no-cache-dir pip 

# install pytest
RUN pip install --no-cache-dir pytest
ARG DPK_WHEEL_FILE_NAME

# Copy and install data processing libraries 
# These are expected to be placed in the docker context before this is run (see the make image).
COPY --chown=ray:users data-processing-dist data-processing-dist
RUN  pip install data-processing-dist/${DPK_WHEEL_FILE_NAME}[ray]

COPY --chown=ray:users src/ src/
COPY --chown=ray:users pyproject.toml pyproject.toml 
COPY --chown=ray:users README.md README.md 
RUN pip install --no-cache-dir -e .

# copy source data
COPY ./src/repo_level_order_transform_ray.py .
COPY ./src/repo_level_order_local_ray.py local/
COPY ./src/repo_level_order_s3_ray.py local/

# copy test
COPY test/ test/
COPY test-data/ test-data/

# Set environment
ENV PYTHONPATH /home/ray:/home/ray/src

# Put these at the end since they seem to upset the docker cache.
ARG BUILD_DATE
ARG GIT_COMMIT
LABEL build-date=$BUILD_DATE
LABEL git-commit=$GIT_COMMIT
