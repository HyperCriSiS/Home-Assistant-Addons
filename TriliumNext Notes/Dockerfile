ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/sh", "-c"]

# Copy data for add-on
COPY run.sh /
RUN chmod a+x /run.sh

# Home Assistant requires these labels
LABEL \
    io.hass.name="TriliumNext Notes" \
    io.hass.description="Hierarchical note-taking application" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}"

# Expose the port
EXPOSE 8080
HEALTHCHECK --start-period=10s CMD exec gosu node node /usr/src/app/docker_healthcheck.cjs

# Set entrypoint
ENTRYPOINT ["/run.sh"]
