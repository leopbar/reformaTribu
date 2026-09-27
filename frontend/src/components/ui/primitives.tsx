/**
 * Componentes base (padrão shadcn/ui sobre Radix UI), com os tokens do sistema "Conferência".
 * Mantidos num único módulo por serem pequenos; cada um é exportado individualmente.
 */
import { cva, type VariantProps } from "class-variance-authority";
import { Check, ChevronDown, X } from "lucide-react";
import {
  Checkbox as CheckboxPrim,
  Dialog as DialogPrim,
  DropdownMenu as DropPrim,
  Label as LabelPrim,
  Popover as PopoverPrim,
  Select as SelectPrim,
  Slot,
  Switch as SwitchPrim,
  Tabs as TabsPrim,
  Tooltip as TooltipPrim,
} from "radix-ui";
import { forwardRef, type ComponentProps, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------------- Button --
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors " +
    "disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 select-none",
  {
    variants: {
      variant: {
        primario: "bg-tinta text-papel hover:bg-tinta-2",
        caneta: "bg-caneta text-white hover:opacity-90 dark:text-papel",
        secundario: "border border-regua-forte bg-superficie text-tinta hover:bg-superficie-2",
        fantasma: "text-tinta-2 hover:bg-superficie-2 hover:text-tinta",
        perigo: "bg-perigo text-white hover:opacity-90 dark:text-papel",
        confirmar: "bg-conferido text-white hover:opacity-90 dark:text-papel",
        link: "text-caneta underline-offset-4 hover:underline px-0 h-auto",
      },
      tamanho: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4 text-sm",
        lg: "h-11 px-5 text-base",
        icone: "h-9 w-9",
        iconeSm: "h-7 w-7",
      },
    },
    defaultVariants: { variant: "secundario", tamanho: "md" },
  },
);

export interface ButtonProps extends ComponentProps<"button">, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, tamanho, asChild, ...props }, ref) => {
    const Comp = asChild ? Slot.Root : "button";
    return <Comp ref={ref} className={cn(buttonVariants({ variant, tamanho }), className)} {...props} />;
  },
);
Button.displayName = "Button";

// --------------------------------------------------------------------------- Input / Label --
export const Input = forwardRef<HTMLInputElement, ComponentProps<"input">>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-9 w-full rounded-md border border-regua-forte bg-superficie px-3 text-sm text-tinta placeholder:text-tinta-3",
      "focus-visible:outline-2 focus-visible:outline-foco aria-[invalid=true]:border-perigo disabled:opacity-60",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, ComponentProps<"textarea">>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "min-h-20 w-full rounded-md border border-regua-forte bg-superficie px-3 py-2 text-sm text-tinta",
      "placeholder:text-tinta-3 aria-[invalid=true]:border-perigo",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export function Label({ className, ...props }: ComponentProps<typeof LabelPrim.Root>) {
  return <LabelPrim.Root className={cn("text-xs font-medium text-tinta-2", className)} {...props} />;
}

export function Campo({
  rotulo,
  erro,
  ajuda,
  children,
  htmlFor,
  className,
}: {
  rotulo: string;
  erro?: string;
  ajuda?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={htmlFor}>{rotulo}</Label>
      {children}
      {erro ? (
        <p role="alert" className="text-2xs text-perigo">
          {erro}
        </p>
      ) : ajuda ? (
        <p className="text-2xs text-tinta-3">{ajuda}</p>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------------------ Checkbox --
export function Checkbox({ className, ...props }: ComponentProps<typeof CheckboxPrim.Root>) {
  return (
    <CheckboxPrim.Root
      className={cn(
        "grid size-4 shrink-0 place-items-center rounded-sm border border-regua-forte bg-superficie",
        "data-[state=checked]:border-caneta data-[state=checked]:bg-caneta data-[state=checked]:text-white",
        className,
      )}
      {...props}
    >
      <CheckboxPrim.Indicator>
        <Check className="size-3" strokeWidth={3} />
      </CheckboxPrim.Indicator>
    </CheckboxPrim.Root>
  );
}

export function Switch({ className, ...props }: ComponentProps<typeof SwitchPrim.Root>) {
  return (
    <SwitchPrim.Root
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-regua-forte transition-colors",
        "data-[state=checked]:bg-conferido",
        className,
      )}
      {...props}
    >
      <SwitchPrim.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </SwitchPrim.Root>
  );
}

// -------------------------------------------------------------------------------- Select --
export function Select({
  valor,
  aoMudar,
  opcoes,
  placeholder,
  id,
  className,
  disabled,
  "aria-label": ariaLabel,
}: {
  valor: string | undefined;
  aoMudar: (v: string) => void;
  opcoes: { valor: string; rotulo: ReactNode }[];
  placeholder?: string;
  id?: string;
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
}) {
  return (
    <SelectPrim.Root value={valor} onValueChange={aoMudar} disabled={disabled}>
      <SelectPrim.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cn(
          "flex h-9 w-full items-center justify-between gap-2 rounded-md border border-regua-forte bg-superficie px-3 text-sm",
          "data-[placeholder]:text-tinta-3",
          className,
        )}
      >
        <SelectPrim.Value placeholder={placeholder} />
        <SelectPrim.Icon>
          <ChevronDown className="size-4 text-tinta-3" />
        </SelectPrim.Icon>
      </SelectPrim.Trigger>
      <SelectPrim.Portal>
        <SelectPrim.Content
          position="popper"
          sideOffset={4}
          className="z-50 max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border border-regua bg-superficie shadow-painel"
        >
          <SelectPrim.Viewport className="p-1">
            {opcoes.map((o) => (
              <SelectPrim.Item
                key={o.valor}
                value={o.valor}
                className="relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-7 pr-2 text-sm outline-none data-[highlighted]:bg-superficie-2"
              >
                <SelectPrim.ItemIndicator className="absolute left-2">
                  <Check className="size-3.5" />
                </SelectPrim.ItemIndicator>
                <SelectPrim.ItemText>{o.rotulo}</SelectPrim.ItemText>
              </SelectPrim.Item>
            ))}
          </SelectPrim.Viewport>
        </SelectPrim.Content>
      </SelectPrim.Portal>
    </SelectPrim.Root>
  );
}

// -------------------------------------------------------------------------------- Dialog --
export const Dialog = DialogPrim.Root;
export const DialogTrigger = DialogPrim.Trigger;
export const DialogClose = DialogPrim.Close;

export function DialogContent({
  titulo,
  descricao,
  children,
  className,
  lateral,
}: {
  titulo: ReactNode;
  descricao?: ReactNode;
  children: ReactNode;
  className?: string;
  lateral?: boolean;
}) {
  return (
    <DialogPrim.Portal>
      <DialogPrim.Overlay className="fixed inset-0 z-40 bg-tinta/30 backdrop-blur-[1px] data-[state=open]:animate-[fade_.15s_ease-out]" />
      <DialogPrim.Content
        className={cn(
          "fixed z-50 flex flex-col gap-4 border border-regua bg-superficie p-6 shadow-painel outline-none",
          lateral
            ? "inset-y-0 right-0 w-full max-w-xl overflow-y-auto data-[state=open]:animate-[entra-lateral_.2s_ease-out]"
            : "left-1/2 top-1/2 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-lg",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <DialogPrim.Title className="text-lg font-semibold">{titulo}</DialogPrim.Title>
            {descricao ? (
              <DialogPrim.Description className="mt-1 text-sm text-tinta-3">{descricao}</DialogPrim.Description>
            ) : (
              <DialogPrim.Description className="sr-only">{String(titulo)}</DialogPrim.Description>
            )}
          </div>
          <DialogPrim.Close asChild>
            <Button variant="fantasma" tamanho="iconeSm" aria-label="Fechar">
              <X />
            </Button>
          </DialogPrim.Close>
        </div>
        {children}
      </DialogPrim.Content>
    </DialogPrim.Portal>
  );
}

// ------------------------------------------------------------------------ Dropdown menu --
export const Menu = DropPrim.Root;
export const MenuTrigger = DropPrim.Trigger;

export function MenuContent({ children, align = "end" }: { children: ReactNode; align?: "start" | "end" }) {
  return (
    <DropPrim.Portal>
      <DropPrim.Content
        align={align}
        sideOffset={6}
        className="z-50 min-w-52 rounded-md border border-regua bg-superficie p-1 shadow-painel"
      >
        {children}
      </DropPrim.Content>
    </DropPrim.Portal>
  );
}

export function MenuItem({ className, ...props }: ComponentProps<typeof DropPrim.Item>) {
  return (
    <DropPrim.Item
      className={cn(
        "flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none",
        "data-[highlighted]:bg-superficie-2 data-[disabled]:opacity-50 [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

export const MenuLabel = ({ children }: { children: ReactNode }) => (
  <DropPrim.Label className="px-2 py-1.5 text-2xs font-medium text-tinta-3">{children}</DropPrim.Label>
);
export const MenuSeparator = () => <DropPrim.Separator className="my-1 h-px bg-regua" />;

// ------------------------------------------------------------------------------ Popover --
export const Popover = PopoverPrim.Root;
export const PopoverTrigger = PopoverPrim.Trigger;
export function PopoverContent({ className, ...props }: ComponentProps<typeof PopoverPrim.Content>) {
  return (
    <PopoverPrim.Portal>
      <PopoverPrim.Content
        sideOffset={6}
        className={cn("z-50 rounded-md border border-regua bg-superficie p-3 shadow-painel", className)}
        {...props}
      />
    </PopoverPrim.Portal>
  );
}

// ------------------------------------------------------------------------------ Tooltip --
export const TooltipProvider = TooltipPrim.Provider;
export function Dica({ texto, children, lado = "top" }: { texto: ReactNode; children: ReactNode; lado?: "top" | "bottom" | "left" | "right" }) {
  return (
    <TooltipPrim.Root delayDuration={300}>
      <TooltipPrim.Trigger asChild>{children}</TooltipPrim.Trigger>
      <TooltipPrim.Portal>
        <TooltipPrim.Content
          side={lado}
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-tinta px-2.5 py-1.5 text-2xs text-papel shadow-painel"
        >
          {texto}
        </TooltipPrim.Content>
      </TooltipPrim.Portal>
    </TooltipPrim.Root>
  );
}

// --------------------------------------------------------------------------------- Tabs --
export const Tabs = TabsPrim.Root;
export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrim.List>) {
  return <TabsPrim.List className={cn("flex gap-1 border-b border-regua", className)} {...props} />;
}
export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrim.Trigger>) {
  return (
    <TabsPrim.Trigger
      className={cn(
        "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-tinta-3 hover:text-tinta",
        "data-[state=active]:border-tinta data-[state=active]:font-medium data-[state=active]:text-tinta",
        className,
      )}
      {...props}
    />
  );
}
export const TabsContent = TabsPrim.Content;

// --------------------------------------------------------------------------- Diversos --
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border border-regua-forte bg-superficie-2",
        "px-1 font-mono text-[11px] text-tinta-2",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-superficie-3", className)} aria-hidden />;
}

export function Separador({ className }: { className?: string }) {
  return <div role="separator" className={cn("h-px w-full bg-regua", className)} />;
}

export function Painel({ className, ...props }: ComponentProps<"section">) {
  return <section className={cn("rounded-lg border border-regua bg-superficie", className)} {...props} />;
}

export function Progresso({ valor, className, rotulo }: { valor: number; className?: string; rotulo: string }) {
  const v = Math.max(0, Math.min(100, valor));
  return (
    <div
      role="progressbar"
      aria-label={rotulo}
      aria-valuenow={Math.round(v)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-superficie-3", className)}
    >
      <div className="h-full bg-tinta transition-[width] duration-500" style={{ width: `${v}%` }} />
    </div>
  );
}

export function Aviso({
  tom = "info",
  titulo,
  children,
  className,
}: {
  tom?: "info" | "atencao" | "erro" | "ok";
  titulo?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const cores = {
    info: "border-regua bg-superficie-2 text-tinta-2",
    atencao: "border-ocre/40 bg-ocre-suave text-tinta",
    erro: "border-perigo/40 bg-perigo-suave text-tinta",
    ok: "border-conferido/40 bg-conferido-suave text-tinta",
  }[tom];
  return (
    <div role={tom === "erro" ? "alert" : "status"} className={cn("rounded-md border px-4 py-3 text-sm", cores, className)}>
      {titulo ? <p className="font-medium text-tinta">{titulo}</p> : null}
      {children ? <div className={cn(titulo && "mt-1")}>{children}</div> : null}
    </div>
  );
}
