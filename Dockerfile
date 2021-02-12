FROM registry.access.redhat.com/ubi8/python-38:latest
USER root
RUN yum -y update
RUN mkdir -p /usr/pycons3rt3
COPY . /usr/pycons3rt3/
WORKDIR /usr/pycons3rt3
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r ./cfg/requirements.txt
RUN python setup.py install

# Build
# docker build -t pycons3rt3:v0.0.8-ubi .

# Run and mount your CONS3RT config directory
# docker run --rm -it -v ~/.cons3rt:/root/.cons3rt pycons3rt3:v0.0.8-ubi

# For the UBI version
# docker run --rm -it -v ~/.cons3rt:/opt/app-root/src/.cons3rt pycons3rt3:v0.0.8-ubi cons3rt cloud list
