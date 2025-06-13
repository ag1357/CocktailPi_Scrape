#!/bin/bash
set -x # Enable debug tracing for verification

echo "Stopping CocktailPi process..."
# Find the PID(s) of the CocktailPi Java process(es) and kill them
PIDS=$(pgrep -f "cocktailpi.jar")

if [ -n "$PIDS" ]; then
    echo "Found CocktailPi process(es) with PID(s): $PIDS. Killing them..."
    sudo kill $PIDS
    # Give it a moment to terminate gracefully
    sleep 5
    # Check if they are still running
    PIDS_AFTER_KILL=$(pgrep -f "cocktailpi.jar")
    if [ -n "$PIDS_AFTER_KILL" ]; then
        echo "Process(es) $PIDS_AFTER_KILL still running. Force killing..."
        sudo kill -9 $PIDS_AFTER_KILL
        sleep 5 # Give it more time after force kill
    fi
else
    echo "CocktailPi process not found or not running."
fi

echo "Deleting CocktailPi database files from /home/pi/..."
# Use the correct database path confirmed by 'find'
sudo rm -f /home/pi/cocktailpi-data.db
sudo rm -f /home/pi/cocktailpi-data.db-shm
sudo rm -f /home/pi/cocktailpi-data.db-wal
echo "Database files deleted (if they existed)."

echo "Starting CocktailPi application from /root/cocktailpi/..."
# Start CocktailPi in the background and redirect output to log file
# The JAR path is correct as /root/cocktailpi/cocktailpi.jar
sudo bash -c '/usr/bin/java -Dsun.misc.URLClassPath.disableJarChecking=true -jar /root/cocktailpi/cocktailpi.jar > /var/log/cocktailpi.log 2>&1 &'

echo "CocktailPi started. Check /var/log/cocktailpi.log for status."
echo "You can now run your import_recipes.py script."
