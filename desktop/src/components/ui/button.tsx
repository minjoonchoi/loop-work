// Adapted from shadcn/ui new-york-v4 Button; MIT, see licenses/SHADCN-MIT.txt
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";
import * as Slot from "@radix-ui/react-slot";

const buttonVariants = cva("button", {
  variants: {
    variant: {
      default: "button-primary",
      destructive: "button-destructive",
      outline: "button-outline",
      secondary: "button-secondary",
      ghost: "button-ghost",
      link: "button-link",
    },
    size: {
      default: "button-size-default",
      xs: "button-size-xs",
      sm: "button-size-sm",
      lg: "button-size-lg",
      icon: "button-size-icon",
      "icon-xs": "button-size-icon-xs",
      "icon-sm": "button-size-icon-sm",
      "icon-lg": "button-size-icon-lg",
    },
  },
  defaultVariants: { variant: "default", size: "default" },
});

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot.Root : "button";

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
