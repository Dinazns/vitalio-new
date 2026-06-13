#!/bin/sh
set -e

echo "Initializing ML engine..."
python -c "from app.ml import engine; engine.init_ml()"

if [ "${MQTT_ENABLED:-true}" = "true" ]; then
  echo "Starting MQTT subscriber..."
  python -c "from app.mqtt_handler import start_mqtt_subscriber; start_mqtt_subscriber()"
fi

echo "Starting: $*"
exec "$@"
