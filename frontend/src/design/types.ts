import type { CSSProperties } from 'react';

export interface DesignNode {
  id: string;
  name: string;
  type: 'text' | 'button' | 'badge' | 'layout' | 'logo';
  w: number;
  h: number;
  dir: 'row' | 'column';
  style: CSSProperties;
  text?: string;
  label?: string;
  variant?: 'primary' | 'secondary';
  children: DesignNode[];
}

export interface Screen {
  key: string;
  nodeId: string;
  name: string;
  route: string;
  url: string;
  role: 'candidate' | 'employer' | 'admin';
  mobile: boolean;
  content: DesignNode;
}
