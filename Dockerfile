FROM python:3
RUN apt-get update
RUN mkdir -p /usr/pycons3rt3
COPY . /usr/pycons3rt3/
WORKDIR /usr/pycons3rt3
RUN pip install --no-cache-dir -r ./cfg/requirements.txt
RUN python setup.py install

# Run and mount your CONS3RT config directory
# docker run --rm -it -v ~/.cons3rt:/root/.cons3rt pycons3rt3:v0
