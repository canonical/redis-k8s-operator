# Redis Operator

A Juju charm deploying and managing Redis on Kubernetes.

# Overview

The [Redis](https://www.redis.io/) operator provides in-memory data structure 
store, used as a database, cache, and message broker. This repository contains a
[Juju](https://jaas.ai/) Charm for deploying Redis on Kubernetes
clusters.

This charm is in development, and it supports a simple Redis topology. Although multiple
units are allowed, replication and clustering are not supported for the moment. You can
track the development in [this](https://github.com/canonical/redis-operator/issues/2) 
and [this](https://github.com/canonical/redis-operator/issues/3) issues, respectively.

# Usage

While this charm is not in the charmstore/charmhub you can build and deploy it locally by:

    charmcraft build
    juju deploy ./redis.charm --resource redis-image=ubuntu/redis

Once Redis starts up it will be running on its default port, 6379. 
To check it you run:

    juju status

to discover the IP Redis is running behind. The output will have lines like:

    Unit       Workload    Agent  Address       Ports     Message
    redis/20   active      idle   10.1.168.69   6379/TCP  Pod is ready.

Then, from your local machine, you can:

    redis-cli -h 10.1.168.69 -p 6379