"""Lifecycle orchestration: pause first, then request cancellation of entries."""
from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.accounting_service import reconcile_paper_account
from tradingagents.research.deployment_repository import DeploymentRepository
from tradingagents.research.execution_contracts import TERMINAL
from tradingagents.research.execution_repository import PaperExecutionRepository, account_key
from tradingagents.research.execution_service import PaperExecutionService
from tradingagents.research.repository import ConflictError


class DeploymentService:
    def __init__(self,sessions,broker):
        self.repo=DeploymentRepository(sessions)
        self.accounting=PaperAccountingRepository(sessions)
        self.execution=PaperExecutionService(PaperExecutionRepository(sessions),broker)
        self.broker=broker

    def observe(self,identifier):
        record=self.repo.detail(identifier)["deployment"]
        if self.accounting.baseline(record.account_key) is None:
            raise ConflictError("Review the account opening baseline in Portfolio → Performance before deployment review")
        return reconcile_paper_account(self.broker,self.accounting,record.account_key)

    def review(self,identifier,action):
        receipt=self.observe(identifier)
        return self.repo.review(identifier,action,receipt.reconciliation_id)

    def activate(self,identifier,action,*,resume=False):
        receipt=self.observe(identifier)
        return self.repo.activate(identifier,action,receipt.reconciliation_id,resume=resume)

    def pause(self,identifier,action):
        # Commit the entry stop even when identity/transport is unavailable.
        record=self.repo.pause(identifier,action)
        return self.cancel_entries(record,action.actor)

    def cancel_entries(self,record,actor,*,symbols=None,created_before=None):
        identifier=record.deployment_id
        outcomes=[]
        for order in self.repo.detail(identifier)["orders"]:
            if order.order["side"]!="buy" or order.state in TERMINAL: continue
            if created_before is not None and order.created_at>created_before: continue
            if symbols is not None and order.order["symbol"] not in symbols: continue
            if order.order.get("stop_loss_usd") is not None or order.order.get("take_profit_usd") is not None:
                outcomes.append({"intent_id":order.intent_id,"state":"protective_entry_requires_review",
                    "reason":"Parent cancellation may remove protective exits. Review remaining entry quantity and protection together; no automatic cancellation was sent."})
                continue
            try:
                self.execution.cancel(order,actor)
                state=self.execution.repo.for_intent(order.intent_id).state
                outcomes.append({"intent_id":order.intent_id,"state":state})
            except Exception as exc:
                outcomes.append({"intent_id":order.intent_id,"state":"cancellation_unavailable","error_type":type(exc).__name__})
        return {"deployment":record,"cancellations":outcomes,"message":"New entries are paused. Unacknowledged orders retain reservations; positions and protective exits are not liquidated."}

    def retire(self,identifier,action):
        receipt=self.observe(identifier)
        return self.repo.retire(identifier,action,receipt.reconciliation_id)

    def evaluate(self,identifier,request,store,*,job_fence=None):
        from tradingagents.research.deployment_evaluation import DeploymentEvaluator
        self.repo.validate_evaluation_request(identifier,request)
        try:
            receipt=self.observe(identifier)
            if not receipt.report["reconciled"] or receipt.report["drawdown_fraction"] is None:
                raise ValueError("Reconciled account history is unavailable")
        except Exception as exc:
            return self.failed_evaluation(identifier,request,"account_observation",exc,job_fence=job_fence)
        try:
            if job_fence:
                from tradingagents.research.deployment_process import evaluate_in_process
                evaluation=evaluate_in_process(self.repo.sessions,identifier,request,receipt.reconciliation_id,store,job_fence=job_fence)
            else:
                evaluation=DeploymentEvaluator(self.repo.sessions).evaluate(identifier,request,receipt.reconciliation_id,store)
        except ConflictError:
            raise  # A stale revision or missed window is a request conflict.
        except Exception as exc:
            return self.failed_evaluation(identifier,request,"source_or_calculation",exc,job_fence=job_fence)
        cancel_cutoff=None
        if job_fence:
            from tradingagents.research.deployment_jobs import live_job
            with self.repo.sessions() as session: cancel_cutoff=live_job(session,*job_fence).started_at
        record=self.repo.detail(identifier)["deployment"]
        if record.state=="paused":
            cancellations=self.cancel_entries(record,request.actor,created_before=cancel_cutoff)["cancellations"]
        else:
            from tradingagents.research.models import StrategyVersionRecord
            from tradingagents.research.repository import require
            with self.repo.sessions() as session:
                spec=require(session,StrategyVersionRecord,record.version_id).payload["spec"]
            symbols={i["symbol"] for i in spec["universe"] if i["instrument_id"] in evaluation.payload.get("cancel_entries",[])}
            cancellations=self.cancel_entries(record,request.actor,symbols=symbols,created_before=cancel_cutoff)["cancellations"] if symbols else []
        return {"evaluation":evaluation,"cancellations":cancellations}

    def failed_evaluation(self,identifier,request,stage,error,*,job_fence=None):
        record=self.repo.evaluation_failed(identifier,request,stage,type(error).__name__,job_fence=job_fence)
        cancel_cutoff=None
        if job_fence:
            from tradingagents.research.deployment_jobs import live_job
            with self.repo.sessions() as session: cancel_cutoff=live_job(session,*job_fence).started_at
        cancellations=self.cancel_entries(record,request.actor,created_before=cancel_cutoff)["cancellations"] if record.state=="paused" else []
        return {"evaluation":None,"deployment":record,"failure":{"stage":stage,"error_type":type(error).__name__},
                "cancellations":cancellations,"message":"Evaluation failed and was recorded. " +
                ("New entries are paused; restore observations and prepare a fresh review before resuming." if record.state=="paused" else "A newer deployment revision is in effect; inspect its current review.")}

    def prepare(self,identifier,request):
        from tradingagents.research.deployment_evaluation import DeploymentEvaluator
        receipt=self.observe(identifier)
        return DeploymentEvaluator(self.repo.sessions).prepare(identifier,request,receipt.reconciliation_id)
