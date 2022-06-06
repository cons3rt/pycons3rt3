FROM jyennaco/python3:v3.10.4

ENV srcDir="/usr/local/src/pycons3rt3"

USER root

RUN dnf -y update \
  && dnf -y install openssh-clients git \
  && dnf -y clean all \
  && rm -rf /var/cache/yum \
  && mkdir -p $srcDir

COPY . $srcDir/

RUN . /etc/profile.d/python.sh \
  && /usr/local/bin/python3 -m pip install --no-cache-dir --upgrade pip \
  && cd $srcDir/ \
  && /usr/local/bin/python3 -m pip install --no-cache-dir -r ./cfg/requirements.txt \
  && /usr/local/bin/python3 setup.py install \
  && rm -Rf $srcDir \
  && echo '#!/bin/bash' > /entrypoint.sh \
  && echo '. /etc/profile.d/python.sh' >> /entrypoint.sh \
  && echo 'exec "$@"' >> /entrypoint.sh \
  && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3"]

# Build
# docker build -t pycons3rt3:v0.0.12a .

# Run and mount your CONS3RT config directory
# docker run --rm -it -v ~/.cons3rt:/root/.cons3rt pycons3rt3:v0.0.12a cons3rt cloud list
