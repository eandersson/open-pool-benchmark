FROM node:24-trixie-slim AS build
RUN apt-get update && apt-get upgrade -y
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 build-essential cmake curl ca-certificates \
    && apt clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
WORKDIR /build
COPY . .
RUN npm i && npm run build

FROM node:24-trixie-slim
EXPOSE 3333 3334 8332
WORKDIR /public-pool
COPY --from=build /build .

RUN npm i -g pm2
ENV NODE_CLUSTER_SCHED_POLICY=none
COPY <<'EOF' ecosystem.config.js
module.exports = {
  apps: [
    {
      name: 'public-pool',
      script: 'dist/main.js',
      exec_mode: 'cluster',
      // Worker count from the harness (= the pinned core count); 'max' = all visible cores if unset.
      instances: process.env.PM2_INSTANCES ? parseInt(process.env.PM2_INSTANCES, 10) : 'max',
    },
  ],
};
EOF
CMD ["pm2-runtime", "start", "ecosystem.config.js"]
