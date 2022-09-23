# Redis Operator

A Juju charm deploying and managing Redis on Kubernetes.

# Overview

The [Redis](https://www.redis.io/) operator provides in-memory data structure 
store, used as a database, cache, and message broker. This repository contains a
Juju Charm for deploying Redis on Kubernetes clusters.

# Usage

To deploy this charm using Juju 2.9.0 or later, run:

    juju deploy redis-k8s --channel edge

The operator supports replication, to deploy several instances of Redis the option
`-n` can be added. The recommended replication size should be at least 3 units:

    juju deploy redis-k8s --channel edge -n <num-units>

Once Redis starts up it will be running on its default port, 6379. 
To check it you run:

    juju status

To discover the IP Redis is running behind. The output will have lines like:

    Unit          Workload  Agent  Address     Ports  Message
    redis-k8s/0*  active    idle   10.1.31.23

To retrieve the password to access the database, use the `get-initial-admin-password` action:

    juju run-action redis-k8s/0 get-initial-admin-password --wait

Then, from your local machine, you can:

    redis-cli -h 10.1.31.23 -a <password> PING

## HA Setup

The operator supports high availability through [Redis Sentinel](https://redis.io/docs/manual/sentinel/).
After being deployed, two containers run on the pod, one with the
redis service, and another one with the sentinel service. Sentinel
runs on its default port, 26379.

A different password is used to setup sentinel. To retrieve it, use
`get-sentinel-password` action:

    juju run-action redis-k8s/0 get-sentinel-password --wait

From a local machine, you can:

    redis-cli -h 10.1.31.23 -p 26379 -a <sentinel-password> PING

## Enabling TLS encryption

The operator has [Redis TLS support](https://redis.io/docs/manual/security/encryption/). Three resources are needed:

- ca-cert-file: CA certificate
- cert-file: X.509 certificate
- key-file: private key

User provided files are accepted. Alternatively, the testing script located on `tests/gen-test-certs.sh` can be used to generate the certificates:

    # The script will create tests/tls/ folders and place the files there.
    ./gen-tesst-certs.sh

To attach generated files as resources:

    juju attach-resource redis-k8s ca-cert-file=tests/tls/ca.crt
    juju attach-resource redis-k8s cert-file=tests/tls/redis.crt
    juju attach-resource redis-k8s key-file=tests/tls/redis.key

After attaching the files, enable TLS with:

    juju config redis-k8s enable-tls=true

Once the application is on an `active|idle` status, you can test connection from your local machine:

    redis-cli -h <host> -a <password> --tls --cacert ./tests/tls/ca.crt PING

# Docs

Docs can be found at https://charmhub.io/redis-k8s/docs?channel=edge

# Libraries

Docs on included libraries for the redis relation can be found at https://charmhub.io/redis-k8s/libraries/redis?channel=edge
