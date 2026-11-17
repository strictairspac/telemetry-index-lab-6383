from src.services import workloads,candidates,experiments,samples
from src.services.audit import log
def save_workload(data,user,item_id=None):
 row=workloads.save(data,item_id);log(user.email,'workload.save',row['name']);return row
def save_candidate(data,user,item_id=None):
 row=candidates.save(data,item_id);log(user.email,'candidate.save',row['name']);return row
def start_experiment(data,user):
 row=experiments.create(data);log(user.email,'experiment.queue',row['name']);return row
def import_samples(data,user):
 row=samples.import_batch(data)
 log(user.email,'sample.import',f"{row['batch_no']} -> {row['status']} rows={row['row_count']} replayed={row['replayed']}")
 return row
