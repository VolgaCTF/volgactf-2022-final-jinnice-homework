# Jinnice Checker: VolgaCTF 2022 Final's checker

This is an after-party-kind-of repo for the overly-stealthy VolgaCTF 2022 Final's `Jinnice` service.

## Build
```bash
$ docker build -t volgactf2022/jinnice-checker-image .
```

## Run
```bash
$ docker run \
    -e SERVICE_IP=<host-ip> \
    -e ROUND_DURATION=10 \
    --rm \
    volgactf2022/jinnice-checker-image
```

## License
MIT @ [VolgaCTF](https://github.com/VolgaCTF)
