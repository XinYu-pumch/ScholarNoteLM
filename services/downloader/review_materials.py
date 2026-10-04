"""Authoritative, run-local material verification outside network callbacks."""
import threading
import status_cache


class InputsChanged(ValueError):
    pass


class Guard:
    def __init__(self, e, expected, compute):
        self.e, self.expected, self.compute = e, expected, compute
        self.validated = None
        self.lock = threading.Lock()

    def verify(self):
        # File identities include inode, size, mtime and ctime, source assets,
        # corpus membership, index generation and model configuration. No TTL
        # and no best-effort UI snapshot may authorize evidence publication.
        with self.lock:
            for _ in range(2):
                before = status_cache.dependencies(self.e)
                if before == self.validated:
                    return
                actual = self.compute()
                after = status_cache.dependencies(self.e)
                if before != after:
                    continue
                if actual != self.expected:
                    raise InputsChanged('材料或检索模型已变化，任务已停止；请重新准备以使用当前证据')
                self.validated = after
                return
            raise InputsChanged('材料正在变化，未发布当前结果；请等待材料更新完成后重试')
