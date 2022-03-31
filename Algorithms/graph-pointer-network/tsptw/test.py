import math
import argparse
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
from torch.optim import lr_scheduler
import matplotlib.pyplot as plt
from tqdm import tqdm
from gpn import GPN
from scipy.spatial import distance

'''
generate training data
'''
def generate_data(B=512, size=50):

    graph = np.random.rand(size, B, 2)
    X = np.zeros([size, B, 4])  # xi, yi, ei, li, ci
    solutions = np.zeros(B) 
    route = [x for x in range(size)] + [0]
    total_tour_len = 0
    
    for b in range(B):
        best = route.copy()
        # begin 2-opt
        graph_ = graph[:,b,:].copy()
            
        dmatrix = distance.cdist(graph_, graph_, 'euclidean')
        improved = True
        
        while improved:
            improved = False
            
            for i in range(size):
                for j in range(i+2, size+1):
                    
                    old_dist = dmatrix[best[i],best[i+1]] + dmatrix[best[j], best[j-1]]
                    new_dist = dmatrix[best[j],best[i+1]] + dmatrix[best[i], best[j-1]]
                    
                    # new_dist = 1000
                    if new_dist < old_dist:
                        best[i+1:j] = best[j-1:i:-1]
                        # print(opt_tour)
                        improved = True  
    
        cur_time = 0
        tour_len = 0
        X[0,b,:2] = graph_[best[0]]  # x0, y0
        X[0,b,2] = 0  # e0 = 0
        X[0,b,3] = 2*np.random.rand(1)  # l0 = rand
        #  X[0,b,4] = 0
        
        for k in range(1, size):
            # generate data with approximate solutions
            X[k,b,:2] = graph_[best[k]]   # xi, yi
            cur_time += dmatrix[best[k-1], best[k]]
            tour_len += dmatrix[best[k-1], best[k]]
            X[k,b,2] = np.max([0, cur_time - 2*np.random.rand(1)])  # entering time 0<= ei <= cur_time
            X[k,b,3] = cur_time + 2*np.random.rand(1) + 1  # leaving time li >= cur_time
            # X[k,b,4] = cur_time    # indicate the optimal solution
        tour_len += dmatrix[best[size-1], best[size]]    
        solutions[b] += tour_len

    # shuffle the original sequence
    np.random.shuffle(X)
    
    X = X.transpose(1,0,2)

    return X, solutions


'''
main
'''

def str2bool(v):
    return v.lower() in ('true', '1')

# args
parser = argparse.ArgumentParser(description="GPN test")
parser.add_argument('--size', default=20, help="size of model")
parser.add_argument('--batch_size', default=1000, help='')
parser.add_argument('--test_size', default=20, help="size of TSP")
parser.add_argument('--random', type=str2bool, default=True, help="random test or held out")
args = vars(parser.parse_args())


size = int(args['size'])
B_val = int(args['batch_size'])    # validation size
save_root ='./model/gpn_tsptw'+str(size)+'.pt'


state = torch.load(save_root)
model = GPN(n_feature=4, n_hidden=128).cuda()
model.load_state_dict(state['model'])

if args['random']:
    X, solutions = generate_data(B=B_val, size=size)
else:
    B_val=10000
    X = np.load('./data/tsptw20_test.npy')
Enter = X[:,:,2]   # Entering time
Leave = X[:,:,3]   # Leaving time


X = torch.Tensor(X).cuda()
Enter = torch.Tensor(Enter).cuda()
Leave = torch.Tensor(Leave).cuda()
mask = torch.zeros(B_val, size).cuda()

baseline = 0
time_wait = torch.zeros(B_val).cuda()
time_penalty = torch.zeros(B_val).cuda()
total_time_cost = torch.zeros(B_val).cuda()
total_time_penalty = torch.zeros(B_val).cuda()

x = X[:,0,:]
h = None
c = None

for k in tqdm(range(size)):

    output, h, c, _ = model(x=x, X_all=X, h=h, c=c, mask=mask)
    idx = torch.argmax(output, dim=1)    # greedy baseline
    
    y_cur = X[[i for i in range(B_val)], idx.data].clone()
    if k == 0:
        y_ini = y_cur.clone()
    if k > 0:
        baseline = torch.norm(y_cur[:,:2] - y_pre[:,:2], dim=1)
        
    y_pre = y_cur.clone()
    x = X[[i for i in range(B_val)], idx.data].clone()

    total_time_cost += baseline
    
    # enter time
    enter = Enter[[i for i in range(B_val)], idx.data]
    leave = Leave[[i for i in range(B_val)], idx.data]
    
    # determine the total reward and current enter time
    time_wait = torch.lt(total_time_cost, enter).float()*(enter - total_time_cost)  
    total_time_cost += time_wait
    
    time_penalty = torch.lt(leave, total_time_cost).float()*10
    # total_time_cost += time_penalty
    total_time_penalty += time_penalty
    
    mask[[i for i in range(B_val)], idx.data] += -np.inf 
total_time_cost += torch.norm(y_cur[:,:2] - y_ini[:,:2], dim=1)

print('validation result:{}, accuracy:{}'
      .format(total_time_cost.mean().item(),
       1-torch.lt(torch.zeros_like(total_time_penalty), total_time_penalty).sum().float() / total_time_penalty.size(0)))
