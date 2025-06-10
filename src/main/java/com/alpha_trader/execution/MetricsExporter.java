package com.alpha_trader.execution;

import io.prometheus.client.Gauge;
import io.prometheus.client.exporter.HTTPServer;

import java.io.IOException;

/**
 * MetricsExporter exposes pnls_total and data_lag_seconds on /metrics.
 * <p>
 * Pass: start() exposes metrics endpoint on specified port; setPnlsTotal() and setDataLagSeconds() update Prometheus gauges.
 * Fail: Throws Exception if server cannot be started or metrics cannot be registered.
 * </p>
 */
public class MetricsExporter {
    private static final Gauge pnlsTotal = Gauge.build()
            .name("pnls_total")
            .help("Total PnL")
            .register();
    private static final Gauge dataLagSeconds = Gauge.build()
            .name("data_lag_seconds")
            .help("Data lag in seconds")
            .register();
    private HTTPServer server;

    /** Start Prometheus endpoint on chosen port. */
    public void start(int port) throws IOException {
        if (server != null) return; // idempotent
        server = new HTTPServer(port);
    }

    /** Stop the HTTP server cleanly. */
    public void stop() {
        if (server != null) {
            server.stop();
            server = null;
        }
    }

    /**
     * Sets the total PnL metric value.
     * @param value the PnL total value
     */
    public void setPnlsTotal(double value) {
        pnlsTotal.set(value);
    }

    /**
     * Sets the data lag metric value in seconds.
     * @param value the lag in seconds
     */
    public void setDataLagSeconds(double value) {
        dataLagSeconds.set(value);
    }
}
