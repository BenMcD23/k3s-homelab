# 3. GPU scheduling on squadron

## Status
Accepted. Documentation only, nothing built yet.

## Context
squadron has a GTX 1070 with 8GB. The plan is to use it for NVENC video
encoding, which currently runs as a plain Docker container on that
machine.

Nothing in this repo touches GPUs yet. This file exists so the work has a
decided shape when it does get built, instead of being improvised later.

## Decision
When this gets built:

- Install the [NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin)
  as a DaemonSet, restricted to squadron with a node selector. home and
  oracle have no NVIDIA GPU, so it must not try to run there.
- Label the node: `kubectl label node squadron gpu=true`
- Taint the node: `kubectl taint node squadron gpu=true:NoSchedule`
- Pods that want the GPU ask for all three:

```yaml
nodeSelector:
  gpu: "true"
tolerations:
  - key: gpu
    value: "true"
    effect: NoSchedule
resources:
  limits:
    nvidia.com/gpu: 1
```

The label and taint are applied by hand, or by a later Ansible task. They
are cluster state, not cloud infrastructure, so Terraform does not manage
them.

## Why both a label and a taint
A label on its own lets GPU pods land on squadron, but does not stop
ordinary pods landing there too and competing for a node whose network is
less dependable.

A taint on its own would mean every other workload in the cluster needs a
toleration, which is backwards.

With both, only pods that explicitly ask for the GPU end up on squadron
for that reason.

## Consequences
- squadron needs the NVIDIA driver and container toolkit installed at the
  OS level before the device plugin can see the card. The `base` Ansible
  role does not cover this. It needs a separate `gpu` role when the time
  comes.
- Not built yet. Written down so it does not need deciding again.
