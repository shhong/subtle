import numpy as np
from tqdm import tqdm
from sklearn.preprocessing import normalize
from sklearn.decomposition import PCA
from openTSNE import TSNE
from umap import UMAP
from subtle.module import morlet_cwt, Data, Phenograph, run_DIB

class Mapper:
    def __init__(self, fs, embedding_method='umap', n_train_frames=120000):
        self.fs=fs
        self.trained=False
        self.n_train_frames = n_train_frames

        self.pca = PCA(100)
        self.umap = UMAP(n_neighbors=50, n_components=2)
        self.pheno = Phenograph()

    def train(self, Xs):
        dataset = [Data(X) for X in Xs]

        for data in tqdm(dataset, desc="Extracting spectrograms"):
            data.S = self.get_spectrogram(data.X)

        S = np.concatenate([data.S for data in dataset])
        S = np.random.permutation(S)[:self.n_train_frames]
        PC = self.pca.fit_transform(S); print('fit PCA done')
        self.Z = self.umap.fit_transform(PC); print('fit UMAP done')
        self.y = self.pheno.fit_predict(self.Z); print('fit Phenograph done')
        self.subclusters = np.unique(self.y)

        for data in tqdm(dataset, desc="Inferring..."):
            data.PC = self.pca.transform(data.S)
            data.Z = self.umap.transform(data.PC)
            data.y = self.pheno.fit_predict(data.Z)
            data.TP, data.R = self.get_transition_probability(data.y)
            data.lambda2 = np.abs(np.linalg.eig(data.TP)[0][1])
            data.tau = -1 / np.log( data.lambda2 ) * 2

        print('Running DIB for creating supercluster...')
        self.avg_tau = sum([data.tau for data in dataset])/len(dataset)
        a = np.concatenate([data.y[:-int(self.avg_tau)] for data in dataset])
        b = np.concatenate([data.y[int(self.avg_tau):] for data in dataset])
        self.supclusters = run_DIB(a, b); print('run DIB complete')

        for data in dataset:
            data.Y = np.array([list(map(lambda y:sup[y], data.y)) for sup in self.supclusters]).T
        

        self.trained = True
        print('Done training.')
        return dataset

    def __call__(self, Xs):
        assert self.trained, 'Model not trained. Train the model first.'
        
        dataset = [Data(X) for X in Xs]        
        for data in tqdm(dataset, desc="Mapping..."):
            data.S = self.get_spectrogram(data.X)
            data.PC = self.pca.transform(data.S)
            data.Z = self.umap.transform(data.PC)
            data.y = self.pheno.predict(data.Z)
            data.TP, data.R = self.get_transition_probability(data.y)
            data.lambda2 = np.abs(np.linalg.eig(data.TP)[0][1])
            data.tau = -1 / np.log( data.lambda2 ) * 2
            data.Y = np.array([list(map(lambda y:sup[y], data.y)) for sup in self.supclusters]).T
        return dataset

    def get_spectrogram(self, X, omega=5, n_channels=50):
        assert isinstance(X, np.ndarray), 'X should be numpy array'
        assert X.ndim==2, 'dimension of X should be 2'
        
        n_frames, n_features = X.shape
        
        cwts = []
        for i in range(n_features):
            x = X[:, i]
            cwt = morlet_cwt(x, fs=self.fs, omega=omega, n_channels=n_channels).T # [n_frames, n_channels]
            cwts.append(cwt)
        cwts = np.hstack(cwts) # [n_frames, n_channels * n_features]
        return cwts

    def get_transition_probability(self, transitions, tau=1):
        states = self.subclusters
        state2index = {k:i for i, k in enumerate(states)}
        transitions = list(map(lambda x: state2index[x], transitions))
        n = len(states)

        M = np.zeros(shape=(n, n))
        for (i,j) in zip(transitions[:-tau], transitions[tau:]):
            M[i, j] += 1
        retention_rate = normalize(M, norm='l1', axis=1).diagonal()
        
        np.fill_diagonal(M, 0)
        transition_probability = normalize(M, norm='l1', axis=1)
        return transition_probability, retention_rate