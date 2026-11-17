import {workloads,candidates,experiments,samples} from '../api/business.js';
export const store={workloads:[],candidates:[],experiments:[],samples:[],user:null};
export async function refresh(){[store.workloads,store.candidates,store.experiments,store.samples]=await Promise.all([workloads.list(),candidates.list(),experiments.list(),samples.list()]);}
