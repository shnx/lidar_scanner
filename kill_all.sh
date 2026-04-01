#!/bin/bash
# Emergency kill script for SLAM Launcher — stops all processes even if UI is stuck

echo "=== SLAM Launcher Emergency Stop ==="

# Kill any python3 main.py instances
pkill -f "python3 main.py" && echo "Stopped python3 main.py"

# Kill any roscore processes on ports 11311–11314
for port in 11311 11312 11313 11314; do
    pid=$(lsof -ti:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo "Stopping roscore on port $port (pid $pid)"
        kill -TERM $pid 2>/dev/null || true
    fi
done

# Kill any remaining roslaunch/roslaunch scripts
pkill -f "roslaunch" && echo "Stopped roslaunch processes"
pkill -f "roscore" && echo "Stopped roscore processes"

# Kill any rosbag record processes
pkill -f "rosbag record" && echo "Stopped rosbag record"

# Wait a moment then force-kill anything left
sleep 2
for port in 11311 11312 11313 11314; do
    pid=$(lsof -ti:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo "Force-killing process on port $port (pid $pid)"
        kill -KILL $pid 2>/dev/null || true
    fi
done

echo "=== Done ==="
