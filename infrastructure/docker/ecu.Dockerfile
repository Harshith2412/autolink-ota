# (unverified: Docker was not available in the build environment)
FROM ubuntu:24.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends g++ make libssl-dev pkg-config && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY ecu/ ./
RUN make && ./build-make/ecu_tests

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends libssl3 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10002 ecu
COPY --from=build /src/build-make/autolink-ecu /usr/local/bin/autolink-ecu
USER ecu
ENTRYPOINT ["autolink-ecu"]
