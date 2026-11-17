/** @typedef {{id:number,name:string,sensor_id:number,start_at:string,end_at:string,device_type:string|null}} Workload */
/** @typedef {{id:number,name:string,workload_id:number,columns:string[]}} Candidate */
/** @typedef {{id:number,name:string,status:'queued'|'running'|'completed'|'failed',batch_no:string|null,result:object|null}} Experiment */
/** @typedef {{id:number,batch_no:string,content_hash:string,row_count:number,status:'importing'|'active'|'retired'|'cleaned'|'failed',table_name:string,error:string|null,activated_at:string|null}} SampleBatch */
export {};
