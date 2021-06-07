FROM jyennaco/python3:v393
USER root
RUN dnf -y update

RUN mkdir -p /usr/pycons3rt3
COPY . /usr/pycons3rt3/
WORKDIR /usr/pycons3rt3
RUN pip3 install --no-cache-dir --upgrade pip
RUN pip3 install --no-cache-dir -r ./cfg/requirements.txt
RUN python3 setup.py install
RUN ln -sf /usr/local/python3/bin/asset /usr/local/bin/asset
RUN ln -sf /usr/local/python3/bin/cons3rt /usr/local/bin/cons3rt
RUN ln -sf /usr/local/python3/bin/deployment /usr/local/bin/deployment
RUN ln -sf /usr/local/python3/bin/pycons3rt_setup /usr/local/bin/pycons3rt_setup
RUN ln -sf /usr/local/python3/bin/s3organizer /usr/local/bin/s3organizer
RUN ln -sf /usr/local/python3/bin/slack /usr/local/bin/slack
WORKDIR /root

# Build
# docker build -t pycons3rt3:v0.0.9 .

# Run and mount your CONS3RT config directory
# docker run --rm -it -v ~/.cons3rt:/root/.cons3rt pycons3rt3:v0.0.9

# For the UBI version
# docker run --rm -it -v ~/.cons3rt:/opt/app-root/src/.cons3rt pycons3rt3:v0.0.9 cons3rt cloud list
