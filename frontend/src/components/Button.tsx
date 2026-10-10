import type { ButtonHTMLAttributes, ReactNode } from 'react';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary';
  children: ReactNode;
}

export function Button({ variant = 'primary', children, className = '', type = 'button', ...rest }: Props) {
  return <button type={type} className={`button button-${variant} ${className}`} {...rest}>{children}</button>;
}
