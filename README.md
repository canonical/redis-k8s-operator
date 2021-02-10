# Redis Operator

A Juju charm deploying and managing Redis on Kubernetes.

# Overview

The [Redis](https://www.redis.io/) operator provides in-memory data structure 
store, used as a database, cache, and message broker. This repository contains a
[Juju](https://jaas.ai/) Charm for deploying Redis on Kubernetes
clusters.

This charm is in development, and it supports simple Redis topology. Although multiple
units are allowed, nor replication nor clustering are supported for the moment. You can
track the development in [this](https://github.com/canonical/redis-operator/issues/2) 
and [this](https://github.com/canonical/redis-operator/issues/3) issues, respectively.

# Usage

    juju deploy redis