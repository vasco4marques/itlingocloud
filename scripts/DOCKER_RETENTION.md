# Docker image retention

The nightly systemd timer keeps:

- every image referenced by a running or stopped container;
- the two newest tagged image IDs for each repository;
- build cache used within the last seven days.

It removes older images and dangling images. It never prunes Docker volumes,
so database and application data are outside the automatic cleanup policy.

Install on the droplet:

```bash
sudo install -m 0755 scripts/docker-image-retention.sh \
  /usr/local/sbin/docker-image-retention
sudo install -m 0644 scripts/docker-image-retention.service \
  /etc/systemd/system/docker-image-retention.service
sudo install -m 0644 scripts/docker-image-retention.timer \
  /etc/systemd/system/docker-image-retention.timer
sudo systemctl daemon-reload
sudo systemctl enable --now docker-image-retention.timer
```

Preview the current policy without deleting anything:

```bash
sudo env DRY_RUN=1 /usr/local/sbin/docker-image-retention
```

Inspect timer and previous-run status:

```bash
systemctl list-timers docker-image-retention.timer
systemctl status docker-image-retention.service
journalctl -u docker-image-retention.service
```
