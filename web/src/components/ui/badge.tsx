import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-auto w-fit shrink-0 items-center justify-center gap-1.5 overflow-hidden rounded-[4px] border px-2 py-0.5 text-[11px] font-mono font-normal tracking-wide whitespace-nowrap transition-colors focus-visible:border-ring focus-visible:ring-[2px] focus-visible:ring-ring/50 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "border-slate-800 bg-slate-900/60 text-slate-200 [a]:hover:bg-slate-800",
        secondary:
          "border-slate-800/80 bg-slate-900/40 text-slate-300 [a]:hover:bg-slate-800/60",
        destructive:
          "border-rose-900/40 bg-rose-950/20 text-rose-300 [a]:hover:bg-rose-950/40",
        outline:
          "border-slate-800 bg-transparent text-slate-300 [a]:hover:bg-slate-900/40",
        ghost:
          "border-transparent bg-transparent text-slate-400 hover:text-slate-200",
        link: "border-transparent text-sky-400 underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
