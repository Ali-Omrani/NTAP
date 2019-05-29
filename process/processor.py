import emoji
import json
import os
import re

import requests
from progressbar import ProgressBar
#from stanfordcorenlp import StanfordCoreNLP
import pandas as pd
import threading
from queue import Queue
import time

# corenlp_path = os.environ.get("CORENLP")
link_re = re.compile(r"(http(s)?[^\s]*)|(pic.twitter.[^\s]*)")
hashtag_re = re.compile(r"#[a-zA-Z0-9_]+")
mention_re = re.compile(r"@[a-zA-Z0-9_]+")
emojis = map(lambda x: ''.join(x.split()), emoji.UNICODE_EMOJI.keys())
emoji_re = re.compile('|'.join(re.escape(p) for p in emojis))

patterns = {"mentions":     mention_re,
            "hashtags":     hashtag_re,
            "links":        link_re
            #"emojis":       emoji_re,
         #   "emoticons":    emoticon_re
           }
print_lock = threading.Lock()
queue = Queue()
class Preprocessor:
    def __init__(self, dest_dir, params):
        self.dest = dest_dir
        if not os.path.isdir(self.dest):
            os.makedirs(self.dest)
        self.source = pd.DataFrame()
        self.data = pd.DataFrame()
        """self.corenlp = StanfordCoreNLP(params["path"]["corenlp_path"], memory='1g')
        self.corenlp_props = {'pipelineLanguage':'en', 'outputFormat':'json'}"""
        self.tagme_token = params["path"]["tagme_token"]
        self.target_cols=params["neural_params"]["target_cols"]
        self.base_dir,self.filename = os.path.split(params['processing']['input_path'])
        self.filename = self.filename.split(".")[0]

    def load(self, file_str, text_col=None, target_cols=None, index_col=None):
        normalize = True
        ending = file_str.split('.')[-1]
        if ending == 'pkl':
            source = pd.read_pickle(file_str)
        if ending == 'csv':
            source = pd.read_csv(file_str, delimiter=',')
        if ending == 'tsv':
            source = pd.read_csv(file_str, delimiter='\t',quoting=3)

        if target_cols is None:
            target_cols = self.target_cols
        for target in target_cols:
            self.data.loc[:, target] = source[target]
            if normalize:
                zscored = ((self.data[target] -
                    self.data[target].mean())/self.data[target].std(ddof=0))
                self.data.loc[:, "{}_zscore".format(target)] = zscored
        if text_col is None:
            text_col = "text"
        self.data.loc[:, text_col] = source[text_col]
        self.text_col = text_col

        if index_col is not None:
            self.data.index = source[index_col].values()

    def __get_target_col(self, cols):
        print("...".join(cols))
        valid_cols = list()
        while len(valid_cols) == 0:
            targets_str = input("Enter target col from those above: ")
            for col in targets_str.split():
                if col not in cols:
                    print("Not a valid column name: {}".format(col))
                else:
                    valid_cols.append(col)
        return valid_cols

    def __get_text_col(self, cols):

        print("...".join(cols))
        notvalid = True
        while notvalid:
            text_col = input("Enter text col from those above: ")
            if text_col.strip() not in cols:
                print("Not a valid column name")
            else:
                notvalid = False
        return text_col

    def clean(self, pat_type, remove=True):
        source = self.data[self.text_col].values.tolist()
        removed = source
        for pattern in pat_type:
            p = patterns[pattern]
            extracted = [p.findall(text) for text in source]
            if remove:
                removed = [p.sub("", text) for text in removed]
                removed = [' '.join(text.split()) for text in removed]
                removed = [x.lower() for x in removed]
            self.data.loc[:, pattern] = pd.Series(extracted, index=self.data.index)
        self.data.loc[:, self.text_col] = pd.Series(removed, index=self.data.index)

    """def pos(self):
        processed, tokens = list(), list()
        self.corenlp_props['annotators'] = 'pos'
        pbar = ProgressBar()
        for doc in pbar(self.data[self.text_col].values):
            annotated = json.loads(self.corenlp.annotate(doc,
                                        properties=self.corenlp_props))
            POSs, words = list(), list()
            for sent in annotated["sentences"]:
                for token in sent["tokens"]:
                    POSs.append(token["pos"])
                    words.append(token["word"])
            processed.append(" ".join(POSs))
            tokens.append(" ".join(words))
        self.data.loc[:, 'tokens'] = pd.Series(tokens, index=self.data.index)
        self.data.loc[:, 'pos'] = pd.Series(processed, index=self.data.index)

    def ner(self):
        processed = list()
        self.corenlp_props['annotators'] = 'ner'
        pbar = ProgressBar()
        for doc in pbar(self.data[self.text_col].values):
            annotated = json.loads(self.corenlp.annotate(doc,
                                properties=self.corenlp_props))
            doc_ner = list()
            for sent in annotated["sentences"]:
                for item in sent["tokens"]:
                    word, ner = item['word'], item["ner"]
                    doc_ner.append( (word, ner) )
            processed.append(doc_ner)
        self.data.loc[:, 'ner'] = pd.Series(processed, index=self.data.index)

    def depparse(self):
        print("Not Implemented (dependency parsing)")"""

    #tagme version 1
    def tagme_v1(self, p=0.1):
        #NOTES:
        #       - If parallelizing, limit to 4 concurrent calls
        #       - Pause (10s) periodically on each thread
        """
        token(str): tagme GCUBE token (requires registration)
        """
        entity_dir = os.path.join(self.dest, "tagme")
        if not os.path.isdir(entity_dir):
            os.makedirs(entity_dir)
        entities = dict()
        extracted = list()
        params = {'gcube-token': self.tagme_token,
                  'lang': 'en',
                  'include_abstract': 'true',
                  'include_categories': 'true'
                 }
        abstract_file = open(os.path.join(entity_dir, "abstracts.tsv"), 'a+')
        abstract_file.seek(0)
        category_file = open(os.path.join(entity_dir, "categories.tsv"), 'a+')
        for line in abstract_file:
            if len(line.strip()) > 0:
                id_, title, _ = line.split('\t')
                entities[id_] = title

        request_str = "https://tagme.d4science.org/tagme/tag"
        count = 0
        try:
            pbar = ProgressBar()
            for doc in pbar(self.data[self.text_col].values):
                count += 1
                if count % 200 == 0:
                    # sleep(5)  # sleep for 5 seconds
                    print("Processed {} docs".format(count))
                    abstract_file.flush()
                    category_file.flush()
                row = list()
                params["text"] = doc
                res = requests.get(request_str, params=params)
                if res.status_code == 200:
                    try:
                        ann = res.json()["annotations"]
                        filt = [entry for entry in ann if entry["link_probability"] > p]
                        for filtered in filt:
                            if filtered["id"] not in entities:
                                entities[filtered["id"]] = filtered["title"]
                                # write entity to file with abstract
                                abstract_file.write("{}\t{}\t{}".format(
                                        filtered["id"], filtered["title"],
                                        filtered["abstract"].replace('\t', '')))
                                abstract_file.write('\n')
                                for cat in filtered["dbpedia_categories"]:
                                    category_file.write("{}\t{}".format(filtered["id"], cat))
                                    category_file.write("\n")
                            # write entity info to list, to save in self.data
                            row.append( (filtered["id"], filtered["start"], filtered["end"], filtered["link_probability"]) )
                    except Exception as e:
                        pass
                else:
                    row.append(("No Response",) )
                extracted.append(row)
        except KeyboardInterrupt:
            partial_index = list(self.data.index)[:len(extracted)]
            saved_data = pd.Series(extracted, index=partial_index)
            print("Interrupted; saved to file")
            saved_data.to_pickle(os.path.join(entity_dir, "saved.pkl"))
            return
        self.data.loc[:, "tagme_entities"] = pd.Series(extracted, index=self.data.index)

    def concat_unique_entity(self, entities, abstract):
        agg_entity = []
        if entities == '':
            return ''
        for entity in entities:
            id = entity[1]
            record = abstract.loc[abstract['Id'] == id]
            title = record['Abstract'].iloc[0]
            if title not in agg_entity:
                agg_entity.append(title)
        agg_str = ' '.join(agg_entity)
        return agg_str


    def aggregate_entities(self, abstract_file_path):
        source = pd.read_csv(abstract_file_path, delimiter='\t', quoting=3, names=['Id', 'Title', 'Abstract'])
        self.data['tagme_aggregated_abstract'] = self.data['tagme_entities'].apply(self.concat_unique_entity, abstract=source)

    def tagme_helper(self, doc, request_str, params, abstract_file, category_file, entities, extracted, p):
        row = list()
        params["text"] = doc[1]
        index = doc[0]
        res = requests.get(request_str, params=params)
        if res.status_code == 200:
            try:
                ann = res.json()["annotations"]
                filt = [entry for entry in ann if entry["link_probability"] > p]
                for filtered in filt:
                    if filtered["id"] not in entities:
                        entities[filtered["id"]] = filtered["title"]
                        # write entity to file with abstract
                        abstract_file.write("{}\t{}\t{}".format(
                            filtered["id"], filtered["title"],
                            filtered["abstract"].replace('\t', '')))
                        abstract_file.write('\n')
                        for cat in filtered["dbpedia_categories"]:
                            category_file.write("{}\t{}".format(filtered["id"], cat))
                            category_file.write("\n")
                    # write entity info to list, to save in self.data
                    row.append((index, filtered["id"], filtered["start"], filtered["end"], filtered["link_probability"]))
            except Exception as e:
                pass
        else:
            row.append(("No Response",))
        if row:
            extracted.append(row)
        return extracted

    def threader(self, request_str, params, abstract_file, category_file, entities, extracted, p, entity_dir):
        while True:
            # gets a worker from the queue
            worker = queue.get()

            # Run the example job with the avail worker in queue (thread)
            self.tagme_helper(worker, request_str, params, abstract_file, category_file, entities, extracted, p)

            #print thread name and doc
            with print_lock:
                print(threading.current_thread().name, worker)

            # completed with the job
            queue.task_done()

    # tagme version 2
    def tagme(self, p=0.1):
        entity_dir = os.path.join(self.dest, "tagme")
        if not os.path.isdir(entity_dir):
            os.makedirs(entity_dir)
        entities = dict()
        extracted = list()
        params = {'gcube-token': self.tagme_token,
                  'lang': 'en',
                  'include_abstract': 'true',
                  'include_categories': 'true'
                 }
        abstract_file = open(os.path.join(entity_dir, "abstracts.tsv"), 'a+')
        abstract_file.seek(0)
        category_file = open(os.path.join(entity_dir, "categories.tsv"), 'a+')
        for line in abstract_file:
            if len(line.strip()) > 0:
                id_, title, _ = line.split('\t')
                entities[id_] = title

        request_str = "https://tagme.d4science.org/tagme/tag"

        start = time.time()
        index = list(range(0, len(self.data[self.text_col])))
        index_dict = dict(zip(index, self.data[self.text_col].values))
        for key, value in index_dict.items():
            queue.put((key, value))

        #intializing 4 threads
        try:
            num_of_threads = 4
            for x in range(num_of_threads):
                t = threading.Thread(target=self.threader, args = (request_str, params, abstract_file, category_file, entities, extracted, p, entity_dir))
                t.daemon = True
                t.start()
            queue.join()

        except KeyboardInterrupt:
            partial_index = list(self.data.index)[:len(extracted)]
            saved_data = pd.Series(extracted, index=partial_index)
            print("Interrupted; saved to file")
            saved_data.to_pickle(os.path.join(entity_dir, "saved.pkl"))
            return
        self.data.loc[:, "tagme_entities"] = pd.Series(extracted, index=[i[0][0] for i in extracted])
        self.data['tagme_entities'].fillna('', inplace=True)
        abstract_file.close()
        category_file.close()
        self.aggregate_entities(abstract_file.name)
        print('Time taken by tagme job(sec):', time.time() - start)


    def write(self, formatting='.json'):
        """
        dest: string or file stream object
        formatting options: json pandas csv tsv
        """
        dest = os.path.join(self.dest, self.filename + formatting)
        if formatting == '.json':
            self.data.to_json(dest)
        if formatting == '.csv':
            self.data.to_csv(dest)
        if formatting == '.tsv':
            self.data.to_csv(dest, sep='\t')
        if formatting == '.pkl':
            self.data.to_pickle(dest)
        if formatting == '.stata':
            self.data.to_stata(dest)
        if formatting == '.hdf5':
            self.data.to_hdf(dest)
        if formatting == '.excel':
            self.data.to_excel()
        if formatting == '.sql':
            self.data.to_sql()

"""
def emojis(df, col):
    emojis_col = list()
    for i, row in df.iterrows():
        text = row[col]

        this_emojis = r.findall(text)
        text = re.sub(emoji_pattern, "", text)

        for emo in emot.emoticons(text):
            if len(emo['value']) > 1:
                this_emojis.append(emo['value'])
                text = text.replace(emo['value'], "")
        emojis_col.append(this_emojis)
        df.at[i, col] = text
    df["emojis"] = pd.Series(emojis_col, index=df.index)
    return df
"""
