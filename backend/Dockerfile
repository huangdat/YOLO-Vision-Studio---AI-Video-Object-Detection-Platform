FROM eclipse-temurin:21-jdk-jammy AS build
WORKDIR /workspace
COPY .mvn .mvn
COPY mvnw pom.xml ./
RUN chmod +x mvnw && ./mvnw -B dependency:go-offline
COPY src src
RUN ./mvnw -B -DskipTests package

FROM eclipse-temurin:21-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system yolovision && useradd --system --gid yolovision yolovision
WORKDIR /app
COPY --from=build --chown=yolovision:yolovision /workspace/target/backend-1.0.0.jar app.jar
USER yolovision
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD curl --fail --silent http://localhost:${SERVER_PORT:-8080}/actuator/health/readiness || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
