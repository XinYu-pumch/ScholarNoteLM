import {t as tr} from './i18n';
import type {ReactNode} from 'react';
import StageMenu from './StageMenu';
/** Shared portal and keyboard contract for all overflow actions. */
export default function ActionMenu({label,children}:{label:string;children:ReactNode}){return <StageMenu label={tr(label)} icon>{children}</StageMenu>;}
