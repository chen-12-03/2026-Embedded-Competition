from queue import Queue
from rknnlite.api import RKNNLite
from concurrent.futures import ThreadPoolExecutor, as_completed
 
 
def initRKNN(rknnModel="./rknnModel/best.rknn", id=0):
    rknn_lite = RKNNLite()
    ret = rknn_lite.load_rknn(rknnModel)
    if ret != 0:
        print("Load RKNN rknnModel failed")
        exit(ret)
    ret = rknn_lite.init_runtime()
    if ret != 0:
        print("Init runtime environment failed")
        exit(ret)
    print(rknnModel, "\t\tdone")
    return rknn_lite
 
 
def initRKNNs(rknnModel="./rknnModel/best.rknn", TPEs=3):
    rknn_list = []
    for i in range(TPEs):
        rknn_list.append(initRKNN(rknnModel, i))
    return rknn_list
 
 
class rknnPoolExecutor():
    def __init__(self, rknnModel, TPEs, func):
        self.TPEs = TPEs
        self.queue = Queue()
        self.rknnPool = initRKNNs(rknnModel, TPEs)
        self.pool = ThreadPoolExecutor(max_workers=TPEs)
        self.func = func
        self.num = 0
 
    def put(self, frame):
        self.queue.put(self.pool.submit(
            self.func, self.rknnPool[self.num % self.TPEs], frame))
        self.num += 1
 
    def get(self):
        if self.queue.empty():
            return None, False
        temp = []
        temp.append(self.queue.get())
        for frame in as_completed(temp):
            return frame.result(), True
 
    def release(self):
        self.pool.shutdown()
        for rknn_lite in self.rknnPool:
            rknn_lite.release()
            
    def get_num(self):
        return self.num 