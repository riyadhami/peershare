/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8080';

const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  async rewrites() {
    return [
      {
        source: '/api/upload',
        destination: `${BACKEND_URL}/upload`,
      },
      {
        source: '/api/download/:port',
        destination: `${BACKEND_URL}/download/:port`,
      },
    ];
  },
}

module.exports = nextConfig
