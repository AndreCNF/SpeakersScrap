from __future__ import unicode_literals, print_function
import spacy
from datetime import timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import newspaper
import yaml
import tqdm
import pendulum
from langdetect import detect
from time import sleep

############################################################################
########################### Auxiliary functions ############################
############################################################################

def set_up_gspread(file_name="Research Speakers", sheet_name="bot_oradores"):
	# use creds to create a client to interact with the Google Drive API
	scope = ['https://spreadsheets.google.com/feeds',
	         'https://www.googleapis.com/auth/drive']
	creds = ServiceAccountCredentials.from_json_keyfile_name('client_secret.json', scope)
	client = gspread.authorize(creds)

	# Open file with the spreadsheets
	file = client.open("Research Speakers")

	# Open a specific spreadsheet from the file
	bot_sheet = file.worksheet("bot_oradores")

	# Get number of filled rows (ignoring the first row as it's an header)
	n_rows = len(bot_sheet.col_values(1)[1:])

	return bot_sheet, n_rows


def load_nlp_models(model_dir):
	# Load custom NLP model trained to find articles about good speakers
	nlp = spacy.load(model_dir)

	# Load English tokenizer, tagger, parser, NER and word vectors
	nlp_en = spacy.load('en')

	# Load Portuguese tokenizer, tagger, parser, NER and word vectors
	nlp_pt = spacy.load('pt')

	return nlp, nlp_en, nlp_pt


def update_spreadsheet(sheet, company, article, row):
	# Insert the names
    sheet.update_cell(row, 1, str(article['people']))
    
    # Wait 1s to avoid Google Sheets API restrictions
    sleep(1)
    
    sheet.update_cell(row, 2, article['nlp_score'])
    
    # Wait 1s to avoid Google Sheets API restrictions
    sleep(1)
    
    sheet.update_cell(row, 3, article['title'])
    
    # Wait 1s to avoid Google Sheets API restrictions
    sleep(1)
    
    sheet.update_cell(row, 4, article['summary'])
    
    # Wait 1s to avoid Google Sheets API restrictions
    sleep(1)
    
    sheet.update_cell(row, 5, company)
    
    # Wait 1s to avoid Google Sheets API restrictions
    sleep(1)
    
    sheet.update_cell(row, 6, article['published'])
    
    # Wait 1s to avoid Google Sheets API restrictions
    sleep(1)
    
    sheet.update_cell(row, 7, article['link'])
    
    # Move on to the next row of the spreadsheet
    row = row + 1
    
    # Wait 1s to avoid Google Sheets API restrictions
    sleep(1)

    return row

############################################################################


# Important variables
config_yaml_dir = "configs/andreferreira_yaml_0.1.yaml"
current_date = pendulum.now('Europe/Lisbon')
model_dir = 'NLP/models/speakers_model_2018_09_23_02_50_37'

bot_sheet, n_rows = set_up_gspread()
nlp, nlp_en, nlp_pt = load_nlp_models(model_dir)

# Start in the first empty row of the spreadsheet
row = n_rows

# Read yaml configuration file, with the requested news sources
with open(config_yaml_dir, 'r') as stream:
    try:
        config_yaml = yaml.load(stream)
    except yaml.YAMLError as exc:
        print(exc)

# Set the limit for number of articles to download, per news source
LIMIT = 20

data = {}
data['newspapers'] = {}

# Iterate through each news company
for company, value in tqdm.tqdm(config_yaml['news_sources'].items()):
    print("Building site for ", company)
    
    # Counting the number of articles read from a news source company
    count = 1
    
    paper = newspaper.build(value['link'], memoize_articles=False)
    newsPaper = {
        "link": value['link'],
        "articles": []
    }
    
    # Counting the number of articles without a readable publish date
    noneTypeCount = 0
    
    for content in paper.articles:
        if count > LIMIT:
            break
            
        try:
            content.download()
            content.parse()
            
        except Exception as e:
            print(e)
            print("continuing...")
            count = count + 1
            continue
            
        # Ignore short texts
        if len(content.text) < 280:
            print("Skipping text of length " + str(len(content.text)))
            count = count + 1
            continue
            
        lang = detect(content.text)
        
        # Ignore texts written in a language that's not portuguese
        if lang != 'pt':
            print("Ignoring text that is written in " + lang + " language.")
            count = count + 1
            continue
            
        # Use the correct language model to find mentions of people
        if lang == 'pt':
            nlp_lang = nlp_pt
        elif lang == 'en':
            nlp_lang = nlp_en
            
        people_list = []
            
        # Get the list of people mentioned in the text
        for entity in nlp_lang(content.text).ents:
            if 'PER' in entity.label_:
                people_list.append(entity.text)
                
        if len(people_list) == 0:
            print("Ignoring text as no mention to people was found.")
            count = count + 1
            continue
            
        # Again, for consistency, if there is no found publish date the article will be skipped.
        # After 10 downloaded articles from the same newspaper without publish date, the company will be skipped.
        if content.publish_date is None:
            print(count, " Article has date of type None...")
            noneTypeCount = noneTypeCount + 1
            if noneTypeCount > 10:
                print("Too many noneType dates, aborting...")
                noneTypeCount = 0
                break
            count = count + 1
            continue
            
        # Get yesterday's date, at the same time (hours, minutes, seconds) as now
        yesterday = current_date - timedelta(days=1)
            
        # If the current article doesn't have a timezone specified, ignore our timezone info to avoid problems
        if content.publish_date.tzinfo == None:
            yesterday = yesterday.replace(tzinfo=None)
            
        # Ignore news articles older than a day ago
        elif content.publish_date < yesterday:
            print("Skipping article from " + str(content.publish_date))
            count = count + 1
            continue
            
        # Score given by the NLP model, indicating the probability that it thinks that the
        # article mentions a good speaker.
        nlp_score = nlp(content.text).cats['POSITIVE']
            
        # Ignore news articles with a bad NLP score
        if nlp_score < 0.8:
            print("Ignoring article with an NLP score of " + str(nlp_score))
            count = count + 1
            continue
            
        article = {}
        article['title'] = content.title
        article['text'] = content.text
        article['link'] = content.url
        article['published'] = content.publish_date.isoformat()
        content.nlp()
        article['keywords'] = content.keywords
        article['summary'] = content.summary
        
        # Add the names of people mentioned in the text
        article['people'] = people_list
        
        # Score given by the NLP model, indicating the probability that it thinks that the
        # article mentions a good speaker.
        article['nlp_score'] = nlp_score
        
        # Add article data to the news source's list
        newsPaper['articles'].append(article)
        print(count, "articles downloaded from", company, "using newspaper, previous article's date: " + 
              content.publish_date.isoformat() + ", url:", content.url)
        count = count + 1
        noneTypeCount = 0

        # Add the current news source's articles data to the whole news list
        data['newspapers'][company] = newsPaper

        row = update_spreadsheet(sheet, company, article, row)
        
try:
    articles_dir = 'results/scraped_articles_' + str(current_date).replace(' ', '_').replace('-', '_') + '.yaml'
    
    with open(articles_dir, 'w') as outfile:
        yaml.dump(data, outfile, allow_unicode=True)
except Exception as e: print(e)