import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "";
const SENHA = process.env.E2E_SENHA ?? "";
const AQUI = path.dirname(fileURLToPath(import.meta.url));
const AMOSTRA = path.resolve(AQUI, "../../data/samples/supermercado_ficticio.xlsx");

test.skip(!EMAIL || !SENHA, "Defina E2E_EMAIL e E2E_SENHA (credenciais de teste do ambiente local).");

test("entrar, enviar planilha, mapear colunas e ver a prévia sem IA", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail").fill(EMAIL);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Carteira de clientes|Painel/);

  // Paleta de comandos
  await page.keyboard.press("Control+K");
  await page.getByPlaceholder("Buscar empresa, auditoria ou ação…").fill("Nova auditoria");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Nova auditoria" })).toBeVisible();

  // Etapa 1: empresa e arquivo
  await page.getByRole("combobox", { name: "Empresa auditada" }).click();
  await page.getByRole("option", { name: /Supermercado Fictício/ }).click();
  await page.locator('input[type="file"]').setInputFiles(AMOSTRA);

  // Etapa 2: mapeamento detectado automaticamente
  await expect(page.getByText("Colunas da planilha")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Descrição do item" })).toContainText("Descrição do Produto");
  await expect(page.getByRole("combobox", { name: "NCM atual" })).toContainText("NCM");
  await page.getByRole("button", { name: "Validar planilha e ver prévia" }).click();

  // Etapas 3 e 4: prévia de problemas (sem IA) e estimativa de custo
  await expect(page.getByRole("heading", { name: "Problemas nos dados" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Zero à esquerda|zero à esquerda/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Estimativa de custo e tempo" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Confirmar .* e iniciar/ })).toBeVisible();
});

test("acessibilidade básica: pular para o conteúdo e tema", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail").fill(EMAIL);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("navigation", { name: "Principal" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Pular para o conteúdo" })).toBeFocused();
  const antes = await page.evaluate(() => document.documentElement.classList.contains("dark"));
  await page.getByRole("button", { name: /Usar tema/ }).click();
  expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(!antes);
});
