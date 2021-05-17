# Redis Operator

A Juju charm deploying and managing Redis on Kubernetes.

# Overview

The [Redis](https://www.redis.io/) operator provides in-memory data structure 
store, used as a database, cache, and message broker. This repository contains a
Juju Charm for deploying Redis on Kubernetes clusters.

# Usage

To deploy this charm using Juju 2.9.0 or later, run:

    juju deploy redis-k8s --channel edge

Once Redis starts up it will be running on its default port, 6379. 
To check it you run:

    juju status

To discover the IP Redis is running behind. The output will have lines like:

    Unit           Workload    Agent  Address       Ports     Message
    redis-k8s/20   active      idle   10.1.168.69   6379/TCP  Pod is ready.

Then, from your local machine, you can:

    redis-cli -h 10.1.168.69

# Docs

Docs can be found at https://charmhub.io/redis-k8s/docs?channel=edge

# Libraries

Docs on included libraries for the redis relation can be found at https://charmhub.io/redis-k8s/libraries/redis?channel=edge
