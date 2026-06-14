import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

export default defineConfig({
  integrations: [
    starlight({
      title: "runloq",
      description: "Local-first issue tracker built for AI coding agents. SQLite + MCP server + React dashboard.",
      tagline: "The backlog your AI coding agent reads, picks up, and closes itself.",
      social: {
        github: "https://github.com/runloq/runloq",
      },
      sidebar: [
        {
          label: "Getting Started",
          items: [
            { label: "Why runloq?", link: "/why/" },
          ],
        },
        {
          label: "Integrations",
          items: [
            { label: "MCP Server", link: "/docs/mcp/" },
            { label: "Claude Code", link: "/docs/claude-code/" },
          ],
        },
        {
          label: "Comparisons",
          items: [
            { label: "vs GitHub Issues", link: "/vs/github-issues/" },
            { label: "vs Linear", link: "/vs/linear/" },
          ],
        },
      ],
      head: [
        {
          tag: "link",
          attrs: {
            rel: "sitemap",
            href: "/sitemap-index.xml",
          },
        },
      ],
      customCss: [],
    }),
  ],
  site: "https://runloq.github.io",
  base: "/runloq",
  trailingSlash: "always",
});
