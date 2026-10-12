ARG BUILD_IMAGE=maven:3.9-eclipse-temurin-17
ARG RUNTIME_IMAGE=eclipse-temurin:17-jre

FROM ${BUILD_IMAGE} AS build
WORKDIR /build
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B -q

FROM ${RUNTIME_IMAGE}
WORKDIR /app
RUN groupadd -r plm && useradd -r -g plm plm
RUN mkdir -p /app/data/uploads && chown -R plm:plm /app
COPY --from=build /build/target/*.jar app.jar
USER plm
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
