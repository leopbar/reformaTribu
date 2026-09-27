import { defineConfig } from "@playwright/test";

/**
 * Testes de ponta a ponta contra o ambiente em execução (`make up`).
 * Credenciais de TESTE via ambiente: E2E_EMAIL e E2E_SENHA (usuário com papel de revisor ou administrador).
 * Por padrão usa o Edge/Chrome instalado (PW_CHANNEL=msedge|chrome) para não baixar navegadores.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5180",
    channel: process.env.PW_CHANNEL ?? "msedge",
    locale: "pt-BR",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
});
