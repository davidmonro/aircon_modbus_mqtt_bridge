FROM alpine AS base
RUN apk add --no-cache python3
RUN pip3 install --upgrade pip setuptools
RUN pip3 install virtualenv
RUN virtualenv /env && /env/bin/pip install paho-mqtt

FROM base as aircon_modbus_mqtt_bridge
RUN /env/bin/pip install pymodbus
COPY aircon_modbus_mqtt_bridge.py .
CMD ["/env/bin/python", "-u", "aircon_modbus_mqtt_bridge.py"]
