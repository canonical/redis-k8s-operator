# Setup, build and deploy

A typical setup using [snaps](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be done using the
following commands.

Install the dependencies:

    sudo snap install juju --classic
    sudo snap install microk8s --classic
    microk8s.enable dns storage
    
Create a controller named `micro` into the cloud `microk8s`:
  
    juju bootstrap microk8s micro

In Juju, you interact with the client (the `juju` command on your local machine). 
It connects to a controller. The controller is hosted on a cloud and controls models.

    juju add-model redis-model

Then you build and deploy this charm into the model you just created:
    
    charmcraft build
    juju deploy ./redis-k8s.charm --resource redis-image=ubuntu/redis

Once Redis starts up it will be running on its default port, 6379. 
To check it you run:

    juju status

to discover the IP Redis is running behind. The output will have lines like:

    Unit          Workload    Agent  Address       Ports     Message
    redis-k8/20   active      idle   10.1.168.69   6379/TCP  Pod is ready.

Then, from your local machine, you can:

    redis-cli -h 10.1.168.69 -p 6379

Another option is to port-forward the Redis pod or service port from k8s to a local port.
For example, forwarding a node's port

    microk8s.kubectl --namespace=redis-model port-forward pod/redis-8485b69dfd-6hgvj 6379:6379

However, it is simpler to forward the service port as it will abstract the node name behind it:

    microk8s.kubectl --namespace=redis-model port-forward service/redis 6379:6379

Then you can simply:

    redis-cli

From a k8s non-charmed scenario Redis will be exposed as `Service` named `redis` on the default
port `6379`.

## Developing

The charm is based on the [operator framework](https://github.com/canonical/operator/). Create and activate 
a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

In order to check the result of a modification, rebuild and upgrade the charm:

    # Consider now that you are inside redis-operator directory.
    charmcraft build
    juju upgrade-charm --path="./redis-k8s.charm" redis-k8s --force-units

Or you can clean up things on different levels, application, model, and controller:

    juju remove-application redis-k8s --force --no-wait
    juju destroy-model redis-model --destroy-storage --force --no-wait
    juju destroy-controller micro --destroy-all-models

## Debugging

In order to enable `TRACE` level at the unit to make everything shows:
    
    juju model-config logging-config="<root>=WARNING;unit=TRACE"

To show the logs for a specific mode:
    
    juju debug-log -m redis-model

To show the logs for all the units in the model:

    microk8s.kubectl get all --namespace=redis-model

To see the logs for a specific pod:
    
    microk8s.kubectl --namespace=redis-model logs redis-k8s-0

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment:

    tox -e unit
    tox -e integration
