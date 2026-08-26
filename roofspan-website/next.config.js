/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export", // static HTML export -> ./out (Railway/static hosting compatible)
  images: { unoptimized: true }, // required for static export
  trailingSlash: true,
  reactStrictMode: true,
};
module.exports = nextConfig;
