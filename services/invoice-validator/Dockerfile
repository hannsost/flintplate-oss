FROM eclipse-temurin:21-jre-alpine

RUN apk add --no-cache curl unzip \
    && mkdir -p /opt/validator/rules \
    && curl -fSL --retry 3 https://github.com/itplr-kosit/validator/releases/download/v1.6.3/validator-1.6.3-standalone.jar -o /opt/validator/validator.jar \
    && echo '799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9  /opt/validator/validator.jar' | sha256sum -c - \
    && curl -fSL --retry 3 https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v2026-08-31/xrechnung-3.0.2-validator-configuration-2026-08-31.zip -o /tmp/rules.zip \
    && echo '2530cd107c414511c5d0462ec10f886910395abfca820db82e83d70bf01221a8  /tmp/rules.zip' | sha256sum -c - \
    && unzip -q /tmp/rules.zip -d /opt/validator/rules \
    && rm /tmp/rules.zip \
    && adduser -D -u 10001 validator

WORKDIR /opt/validator/rules
USER validator
CMD ["java", "-Xmx384m", "-XX:ActiveProcessorCount=2", "-jar", "/opt/validator/validator.jar", "-s", "scenarios.xml", "-r", "/opt/validator/rules", "-D", "-H", "0.0.0.0", "-P", "8080", "--disable-gui"]
