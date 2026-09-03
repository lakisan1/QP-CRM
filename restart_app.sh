#!/usr/bin/env bash
# Restart the QP-CRM merged app cleanly

cd /home/lazar/Desktop/Posao/Programs/QP-CRM

echo "Stopping old instances..."
for pid in $(pgrep -f "[p]ython main.py"); do
  echo "Killing PID $pid"
  kill "$pid" 2>/dev/null || true
done
sleep 3

# Double-check nothing is on port 5000
if command -v fuser >/dev/null 2>&1; then
  fuser -k 5000/tcp 2>/dev/null || true
fi
sleep 1

echo "Starting app..."
setsid ./venv/bin/python main.py > main.log 2>&1 &
disown

sleep 4
echo "=== Last lines of main.log ==="
tail -n 8 main.log
echo ""
echo "App should be running at http://localhost:5000"