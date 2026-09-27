import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useAuth } from "@/auth/auth";
import { AvisoResponsabilidade, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Input } from "@/components/ui/primitives";

const esquema = z.object({
  email: z.string().trim().email("Informe um e-mail válido."),
  senha: z.string().min(1, "Informe a senha."),
});
type Dados = z.infer<typeof esquema>;

export function LoginPage() {
  const { entrar } = useAuth();
  const navegar = useNavigate();
  const [erro, setErro] = useState<string | null>(null);
  const f = useForm<Dados>({ resolver: zodResolver(esquema) });

  const enviar = f.handleSubmit(async (d) => {
    setErro(null);
    try {
      await entrar(d.email, d.senha);
      await navegar({ to: "/" });
    } catch (e) {
      setErro(mensagemErro(e));
    }
  });

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-regua bg-superficie p-12 lg:flex">
        <div className="flex items-center gap-2">
          <img src="/marca.svg" alt="" className="size-8" />
          <span className="font-semibold">Auditor Fiscal de Cadastros</span>
        </div>
        <div className="max-w-lg">
          <p className="codigo text-sm text-tinta-3">LC 214/2025 · IBS · CBS · IS</p>
          <h1 className="mt-3 text-2xl leading-tight">
            Cada NCM conferido contra a descrição do item, antes que a nota fiscal saia errada.
          </h1>
          <div className="mt-10 space-y-2" aria-hidden>
            <LinhaExemplo antes="3401.11.90" depois="3401.30.00" texto="SAB LIQ ERVA DOCE 250ML" />
            <LinhaExemplo antes="0401.10.10" depois="0401.10.10" texto="LEITE UHT INTEGRAL 1L" ok />
            <LinhaExemplo antes="2009.61.00" depois="?" texto="SUCO UVA 1L" duvida />
          </div>
        </div>
        <AvisoResponsabilidade className="max-w-md" />
      </section>

      <section className="flex items-center justify-center p-6">
        <form onSubmit={enviar} className="w-full max-w-sm space-y-5" noValidate>
          <div>
            <h2 className="text-xl">Entrar</h2>
            <p className="mt-1 text-sm text-tinta-3">Use o e-mail e a senha fornecidos pelo administrador.</p>
          </div>
          {erro ? <Aviso tom="erro">{erro}</Aviso> : null}
          <Campo rotulo="E-mail" htmlFor="email" erro={f.formState.errors.email?.message}>
            <Input id="email" type="email" autoComplete="username" autoFocus aria-invalid={!!f.formState.errors.email} {...f.register("email")} />
          </Campo>
          <Campo rotulo="Senha" htmlFor="senha" erro={f.formState.errors.senha?.message}>
            <Input id="senha" type="password" autoComplete="current-password" aria-invalid={!!f.formState.errors.senha} {...f.register("senha")} />
          </Campo>
          <Button type="submit" variant="primario" className="w-full" disabled={f.formState.isSubmitting}>
            {f.formState.isSubmitting ? "Entrando…" : "Entrar"}
          </Button>
        </form>
      </section>
    </div>
  );
}

function LinhaExemplo({ antes, depois, texto, ok, duvida }: { antes: string; depois: string; texto: string; ok?: boolean; duvida?: boolean }) {
  return (
    <div className="flex items-center gap-4 rounded-md border border-regua bg-papel px-4 py-2.5 text-sm">
      <span className="w-52 truncate text-tinta-2">{texto}</span>
      <span className={ok ? "codigo text-conferido" : "codigo text-ocre line-through decoration-ocre/70"}>{antes}</span>
      {!ok ? <span className={duvida ? "codigo text-ocre" : "codigo traco-caneta text-caneta"}>{depois}</span> : null}
    </div>
  );
}
