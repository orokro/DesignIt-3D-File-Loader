/*
	d3dl.js
	-------

	DesignIt-3D Loader.
*/

// load list of headers for parsing the file
const vvrHeaders = require('./VVRHeaders.js');

// use file system so we can load the binary file
const fs = require('fs');

// get the file to load,
// for now we'll also always default to "JUSTCUBE.VVR" for debugging
const fileToLoad = (process.argv[2] || 'JUSTCUBE.VVR');

// load the file's binary
const fileBuffer = fs.readFileSync(`./${fileToLoad}`);

// to start, we'll loop over the entire buffer, looking for combinations of four uppercase letters
// that match one of our vvrHeaders.
// then, we'll continue recording binary until we hit another header or EOF

// array of VVR sections we'll populate
const sections = [];

// buffer of last four while we look for our keywords
let lastFour = [];

// current section data we're gathering, null till we find our first section
let currentSection = null;

// loop over buffer data
for (x of fileBuffer) {

	// if we have a current object, push the data to it's data section
	if(currentSection!=null)
		currentSection.data.push(x);
		
	// get character from buffer byte
	const c = String.fromCharCode(x);

	// add to our last four & unshift the front if we're over 4 total
	lastFour.push(c);
	while(lastFour.length>4)
		lastFour.shift();

	// get the last-four as a single 4-digit string.
	const lastFourStr = lastFour.join('');

	// check if the last four match one of our headers & start a new section if we did
	if(vvrHeaders.includes(lastFourStr)){

		// first, we if have an existing object, we should remove the last four from it's data section
		if(currentSection!=null)
			for(let i=0; i<4; i++)
				currentSection.data.pop();

		// make a new section object using our last four as it's header type
		const newSection = {
			header: lastFourStr,
			data: [],
		};
		sections.push(newSection);

		// set as our new current section
		currentSection = newSection;
	}

}// next x
  
// for now, let's just loop over and print the data we found in a logical way
for(section of sections){
	
	console.log("---------------------------------------");
	console.log(section.header);
	if(section.data.length>0)
		console.log(section.data.join(', '));

}// next section
