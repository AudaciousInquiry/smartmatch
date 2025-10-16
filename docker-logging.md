# Docker Logging Commands

Docker logging is essential for debugging and monitoring your services. Here are the most useful commands:

## Basic Commands

```shell
# View last 20 lines of backend API logs
docker compose logs app --tail 20

# View last 50 lines of frontend logs
docker compose logs frontend --tail 50

# Follow logs in real-time (shows new log entries as they occur)
docker compose logs app --follow
docker compose logs frontend --follow

# Follow logs for ALL services in real-time
docker compose logs --follow

# View last 20 lines AND follow new entries (most useful for debugging)
docker compose logs app --tail 20 --follow

# Run logs in background (note the '&' at the end)
# Useful when you want logs running while you work in the same terminal
docker compose logs app --tail 20 --follow &

# View logs with timestamps
docker compose logs app --timestamps

# View logs for multiple services at once
docker compose logs app frontend --tail 50 --follow

# View logs since a specific time
docker compose logs app --since 30m    # Last 30 minutes
docker compose logs app --since 2h     # Last 2 hours
docker compose logs app --since 2025-01-15T10:00:00

# Combine options for powerful debugging
docker compose logs app --tail 100 --follow --timestamps
```

## Common Logging Scenarios

### 1. Debugging an API error
```shell
docker compose logs app --tail 50 --follow
# Then trigger the error in your browser and watch the logs
```

### 2. Monitoring multiple services
```shell
docker compose logs app frontend --follow
```

### 3. Checking database connection issues
```shell
docker compose logs postgres --tail 100
```

### 4. Background monitoring while developing
```shell
docker compose logs app --tail 20 --follow &
# Continue working in the same terminal
```

### 5. Debugging frontend build issues
```shell
docker compose logs frontend --tail 200
```

## Pro Tips

- Use `--tail N` to limit output and avoid overwhelming your terminal
- Use `--follow` (or `-f`) to see logs in real-time as they happen
- Press `Ctrl+C` to stop following logs
- Use `&` at the end to run logs in background (Bash only)
- Combine `--tail` and `--follow` for the best debugging experience
