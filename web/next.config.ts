import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Allow reading files from the parent data/ directory
  serverExternalPackages: [],
  // Disable x-powered-by header
  poweredByHeader: false,
}

export default nextConfig
