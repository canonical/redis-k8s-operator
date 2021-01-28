# redis-operator

## Description

The [Redis](https://www.redis.io/) operator provides in-memory data structure 
store, used as a database, cache, and message broker. This repository contains a
[Juju](https://jaas.ai/) Charm for deploying Redis on Kubernetes
clusters.

## Setup, build and deploy

A typical setup using [snaps](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be done using the
following commands

    sudo snap install juju --classic
    sudo snap install microk8s --classic
    microk8s.enable dns storage
    juju bootstrap microk8s micro
    juju add-model redis-model
    charmcraft build
    juju deploy ./redis.charm --resource redis-image=redis:6.0

To access Redis you run

    juju status

to discover the IP Redis is running behind. The output will have lines like

    Unit       Workload    Agent  Address       Ports     Message
    redis/20   active      idle   10.1.168.69   6379/TCP  Pod is ready.

Then you can 

    redis-cli -h 10.1.168.69 -p 3000

Another option is to port-forward the Redis service (or pod) port from k8s to a local port.
For example, forwarding a node's port

    microk8s.kubectl --namespace=redis-model port-forward pod/redis-8485b69dfd-6hgvj 6379:6379

However, it is simpler to forward the service port as it will abstract the node name behind it

    microk8s.kubectl --namespace=redis-model port-forward service/redis 6379:6379

Then you can simply

    redis-cli

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

In order to check the result of a modification, rebuild and upgrade the charm

    charmcraft build
    juju upgrade-charm --path="/home/eduardo/Canonical/redis-k8s/redis.charm" redis --force-units

Or you can clean up things on different levels, application, model, and controller

    juju remove-application redis --force --no-wait
    juju destroy-model redis-model --destroy-storage --force --no-wait
    juju destroy-controller micro --destroy-all-models

## Debugging

In order to enable `TRACE` level at the unit to make everything shows
    
    juju model-config logging-config="<root>=WARNING;unit=TRACE"

To show the logs for a specific mode
    
    juju debug-log -m redis-model

To show the logs for all the units in the model

    microk8s.kubectl get all --namespace=redis-model

To see the logs for a specific pod
    
    microk8s.kubectl --namespace=redis-model logs redis-operator-0

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
